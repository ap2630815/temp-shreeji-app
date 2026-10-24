"""Demo history: a year of business spread over the months, so the "by month" charts on /Analysis have bars to show.

    python -m scripts.seed_history            # insert (refuses to run twice; needs the demo masters from scripts.seed_demo)
    python -m scripts.seed_history --remove   # delete exactly the rows this script inserted
    python -m scripts.seed_history 2024-25    # another business year (default: the one before the current)
    python -m scripts.seed_history --chains=15  # chains per month (default 10; at most 20)

Each month gets purchases -> bookings -> trips -> weighed bilties, then receipts, payments, labour work and bag supplies, built with the
same services the screens use. Closed years refuse new entries on the screens, so the year check is lifted for this script only.
Every inserted id is recorded in scripts/.history_ids.json so removal never touches other data."""

import asyncio
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import SessionLocal, engine
from app.models import (
    AuditLog, BagSupply, Bilty, BrokerBooking, Brokerage, Farmer, Grain, Industry, LabourGroup, LabourWork, Payment, PaymentAllocation, PurchaseFarmerEntry,
    PurchaseGroup, PurchaseGroupFarmer, Receipt, ReceiptAllocation, Truck, Transporter, TruckLoadLine, TruckTrip, User, BagSupplier,
)
from app.services import audit
from app.services import payables as pay_svc
from app.services import receivables as rec_svc
from app.services.money import payable_amount, total_available_bags
from app.services.years import business_year_of, current_year_label

IDS_FILE = Path(__file__).with_name(".history_ids.json")
CHAINS_PER_MONTH = 10  # purchase -> booking -> trip -> bilty chains per month; --chains=N overrides
rng = random.Random(77)


async def _open_year(db, d):  # the screens close past years; this script writes history on purpose
    return business_year_of(d)


def _months(label: str) -> list[tuple[int, int]]:
    start = int(label[:4])
    return [(start, m) for m in (10, 11, 12)] + [(start + 1, m) for m in range(1, 10)]


async def seed(label: str, chains: int) -> None:
    if IDS_FILE.exists():
        sys.exit(f"History already seeded ({IDS_FILE.name} exists). Run with --remove first.")
    pay_svc.assert_year_open = rec_svc.assert_year_open = _open_year
    ids: dict[str, list[int]] = {k: [] for k in (
        "purchase_group", "purchase_group_farmers", "purchase_farmers_entries", "broker_bookings", "truck_trips", "truck_load_lines", "bilties", "labour_work",
        "bag_supplies", "receipts", "payments")}
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.role == "owner").order_by(User.id))
        if user is None:
            sys.exit("Create an owner user first (scripts.create_user).")
        farmers = list((await db.scalars(select(Farmer).order_by(Farmer.id))).unique().all())
        grains = {g.id: g for g in (await db.scalars(select(Grain))).unique().all()}
        brokerages = list((await db.scalars(select(Brokerage).order_by(Brokerage.id))).unique().all())
        industries = list((await db.scalars(select(Industry).order_by(Industry.id))).unique().all())
        trucks = list((await db.scalars(select(Truck).order_by(Truck.id))).unique().all())
        transporters = list((await db.scalars(select(Transporter).order_by(Transporter.id))).unique().all())
        groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.id))).unique().all())
        suppliers = list((await db.scalars(select(BagSupplier).order_by(BagSupplier.id))).unique().all())
        if not (farmers and brokerages and industries and trucks and transporters and groups and suppliers):
            sys.exit("Masters are missing. Run scripts.seed_demo first.")
        bill_no = 1000  # clear of the demo bilties (201..), unique per business year
        broker_of = {b.id: b.broker_id for b in brokerages}
        n = 0
        for mi, (yr, mo) in enumerate(_months(label)):
            day = lambda d: date(yr, mo, d)  # noqa: E731
            if day(28) >= date.today():
                break  # never write into the future
            booked = []
            step = max(1, 20 // chains)
            for k in range(chains):
                base = 1 + k * step  # purchase on base, booking +1, trip +2, bilty +4: all before the receipts on the 24th
                n += 1
                f = farmers[(mi * chains + k) % len(farmers)]
                br = brokerages[(mi + k) % len(brokerages)]
                grain = grains[br.grain_id]
                rate = max(300, int(grain.net_bag_weight * 20 * 0.9 + rng.randint(-60, 120)))
                pd_ = day(base)
                grp = PurchaseGroup(purchase_group_date=pd_, business_year=label, village_id=f.village_id, grain_id=grain.id, grain_rate_per_20kg=rate,
                                    pay_after_no_of_days=[7, 10, 15, 20][k % 4], purchase_group_terms=grain.grain_terms, description="Demo history", created_by=user.id)
                db.add(grp)
                await db.flush()
                db.add(PurchaseGroupFarmer(purchase_group_id=grp.id, farmer_id=f.id, created_by=user.id))
                await db.flush()
                net = grain.net_bag_weight
                bags, kilos = rng.randint(120, 400), rng.choice([0, 0, rng.randint(5, net - 1)])
                handful = rng.choice([0, 0, 3, 5])
                amount = payable_amount(bags, kilos, net, rate)
                entry = PurchaseFarmerEntry(
                    purchase_entry_date=pd_, business_year=label, purchase_group_id=grp.id, farmer_id=f.id, labour_group_id=groups[n % len(groups)].id,
                    no_of_filled_bags=bags, extra_kilos=kilos, no_of_handful_bags=handful, total_available_bags=total_available_bags(bags, handful),
                    payable_amount=amount, borrowed_amount=rng.choice([0, 0, 500, 1000]) if amount > 3000 else 0, due_date=pd_ + timedelta(days=grp.pay_after_no_of_days),
                    expected_raw_weight_per_bag=net + rng.randint(0, 2), description="Demo history", created_by=user.id)
                bd = day(base + 1)
                booking = BrokerBooking(booking_date=bd, business_year=label, brokerage_id=br.id, industry_id=industries[(mi + k) % len(industries)].id,
                                        grain_rate_per_booking_weight=-(-int(rate * 1.08) // 10) * 10 * (5 if grain.booking_weight == 100 else 1),
                                        truck_size=[10, 15, 20, 25, 30][k % 5], percentage_deduction=rng.choice([None, 0.5, 1, 2]), description="Demo history", created_by=user.id)
                db.add_all([entry, booking])
                await db.flush()
                td = day(base + 2)
                per_ton = n % 2 == 0
                trip = TruckTrip(trip_date=td, business_year=label, broker_booking_id=booking.id, truck_id=trucks[n % len(trucks)].id,
                                 transporter_id=transporters[n % len(transporters)].id, labour_group_id=groups[(n + 1) % len(groups)].id,
                                 rent_per_ton=rng.randrange(700, 1300, 50) if per_ton else 0, rent_per_bag=0 if per_ton else rng.randint(15, 30),
                                 advance_amount=rng.choice([0, 500, 1000, 2000]), other_payable=rng.choice([0, 0, 300]), other_deduction=0,
                                 description="Demo history", created_by=user.id)
                db.add(trip)
                await db.flush()
                loaded = int(entry.total_available_bags * 0.8)
                line = TruckLoadLine(trip_id=trip.id, purchase_farmer_entry_id=entry.id, no_of_loaded_bags=loaded, total_remaining_bags=entry.total_available_bags - loaded)
                m_net = loaded * net + rng.randint(0, 40)
                m_tare = rng.randrange(9000, 11000, 10)
                i_net = m_net - int(m_net * rng.uniform(0.0, 0.008))
                i_tare = m_tare + rng.randint(-20, 20)
                bill_no += 1
                bilty = Bilty(truck_trip_id=trip.id, business_year=label, bilty_date=day(base + 4), bill_number=bill_no, total_bags_in_truck=loaded,
                              any_rate_change=rng.choice([0, 0, 0, 5]), merchant_total_weight=m_net + m_tare, merchant_tare_weight=m_tare,
                              industry_total_weight=i_net + i_tare, industry_tare_weight=i_tare, description="Demo history", created_by=user.id)
                db.add_all([line, bilty])
                await db.flush()
                booked.append((grp, entry, booking, trip, line, bilty))
                for key, row in (("purchase_group", grp), ("purchase_farmers_entries", entry), ("broker_bookings", booking), ("truck_trips", trip),
                                 ("truck_load_lines", line), ("bilties", bilty)):
                    ids[key].append(row.id)
                    if key != "truck_load_lines":
                        audit.log(db, user, "create", key, row.id, {"demo": True})
                ids["purchase_group_farmers"].extend(j for j in (await db.scalars(select(PurchaseGroupFarmer.id).where(PurchaseGroupFarmer.purchase_group_id == grp.id))).all())
            # labour work and a bag supply for the month
            lw = LabourWork(labour_group_id=groups[mi % len(groups)].id, work_date=day(10), business_year=label, payable_amount=rng.randrange(3000, 9000, 100),
                            borrowing_amount=rng.choice([0, 0, 500]), petrol=rng.choice([0, 200, 300]), meal=rng.choice([0, 150, 250]), description="Demo history", created_by=user.id)
            rate_bag, nbags = rng.randint(12, 25), rng.randrange(200, 600, 50)
            bs = BagSupply(supplier_id=suppliers[mi % len(suppliers)].id, farmer_id=farmers[mi % len(farmers)].id, supply_date=day(6), business_year=label,
                           rate_per_bag=rate_bag, no_of_bags=nbags, payable_amount=rate_bag * nbags, description="Demo history", created_by=user.id)
            db.add_all([lw, bs])
            await db.flush()
            ids["labour_work"].append(lw.id)
            ids["bag_supplies"].append(bs.id)
            audit.log(db, user, "create", "labour_work", lw.id, {"demo": True})
            audit.log(db, user, "create", "bag_supplies", bs.id, {"demo": True})
            await db.commit()

            # receipts (money in): four per month, from industries whose bilties are already dated before the receipt
            for rd in (day(24), day(25), day(27), day(28)):
                views = [v for v in await rec_svc.bilty_views(db) if v.due and v.due > 0 and v.bilty.bilty_date <= rd and v.bilty.business_year == label]
                if not views:
                    continue
                v = views[rng.randrange(len(views))]
                ind = v.bilty.trip.industry
                due = sum(x.due for x in views if x.bilty.trip.industry.id == ind.id)
                amount = min(due, max(10000, round(due * rng.choice([0.3, 0.5, 0.7]), -3)))
                method = rng.choice(["bank", "upi", "cheque"])
                r = await rec_svc.record_receipt(db, user, ind.id, dict(receipt_date=rd, amount=amount, method=method, reference_no=f"{method[:3].upper()}{rng.randint(100000, 999999)}",
                                                                        payer_name=ind.owner_name, description="Demo history"))
                await db.commit()
                ids["receipts"].append(r.id)

            # payments (money out): a farmer, a truck owner, a broker, the labour group and the bag supplier of this month
            grp, entry, booking, trip, *_ = booked[0]
            pd2 = day(28)
            plan = [("farmer", entry.farmer_id), ("truck", trip.truck_id), ("broker", broker_of[booking.brokerage_id]), ("labour_group", lw.labour_group_id), ("bag_supplier", bs.supplier_id)]
            for j, (ptype, pid) in enumerate(plan):
                rows = [p for p in await pay_svc.load_payables(db, ptype, pid) if p.due > 0 and p.sort_key[0] <= pd2]
                if not rows:
                    continue
                due = sum(p.due for p in rows)
                amount = min(due, max(500, round(due * rng.choice([0.3, 0.5, 0.6]), -2)))
                party = await pay_svc.get_party(db, ptype, pid)
                rname, rmobile = pay_svc.PARTIES[ptype].receiver(party)
                rmobile = rmobile or f"9{mi:03d}0{j + 1:05d}"
                method = ["cash", "upi", "bank"][j % 3]
                p = await pay_svc.record_payment(db, user, ptype, pid, dict(
                    payment_date=pd2, amount=amount, method=method, receiver_name=rname, receiver_mobile=rmobile,
                    reference_no=None if method == "cash" else f"REF{rng.randint(100000, 999999)}", description="Demo history"))
                await db.commit()
                ids["payments"].append(p.id)
    IDS_FILE.write_text(json.dumps(ids, indent=1))
    await engine.dispose()
    print(f"Inserted demo history for {label}:")
    for name, v in ids.items():
        print(f"  {name:26} {len(v)}")


async def remove() -> None:
    if not IDS_FILE.exists():
        sys.exit("No demo history recorded (nothing to remove).")
    ids = json.loads(IDS_FILE.read_text())
    async with SessionLocal() as db:
        pay_ids, rec_ids = ids.get("payments", []), ids.get("receipts", [])
        await db.execute(delete(PaymentAllocation).where(PaymentAllocation.payment_id.in_(pay_ids)))
        await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
        await db.execute(delete(ReceiptAllocation).where(ReceiptAllocation.receipt_id.in_(rec_ids)))
        await db.execute(delete(Receipt).where(Receipt.id.in_(rec_ids)))
        for model, key in ((Bilty, "bilties"), (TruckLoadLine, "truck_load_lines"), (TruckTrip, "truck_trips"), (BrokerBooking, "broker_bookings"),
                           (BagSupply, "bag_supplies"), (LabourWork, "labour_work"), (PurchaseFarmerEntry, "purchase_farmers_entries"),
                           (PurchaseGroupFarmer, "purchase_group_farmers"), (PurchaseGroup, "purchase_group")):
            await db.execute(delete(model).where(model.id.in_(ids.get(key, []))))
        for table in ("purchase_group", "purchase_farmers_entries", "broker_bookings", "truck_trips", "bilties", "labour_work", "bag_supplies", "payments", "receipts"):
            await db.execute(delete(AuditLog).where(AuditLog.table_name == table, AuditLog.record_id.in_(ids.get(table, []))))
        await db.commit()
    IDS_FILE.unlink()
    await engine.dispose()
    print("Demo history removed.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--remove" in sys.argv:
        asyncio.run(remove())
    else:
        y = args[0] if args else f"{int(current_year_label()[:4]) - 1}-{int(current_year_label()[:4]) % 100:02d}"
        chains = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--chains=")), CHAINS_PER_MONTH)
        asyncio.run(seed(y, min(max(chains, 1), 20)))
