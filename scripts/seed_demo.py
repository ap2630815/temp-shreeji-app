"""Demo data: 10 rows in every master and transaction table, built with the same rules the screens use.

    python -m scripts.seed_demo            # insert (refuses to run twice)
    python -m scripts.seed_demo --remove   # delete exactly the rows this script inserted

Every inserted id is recorded in scripts/.demo_ids.json so removal never touches real data."""

import asyncio
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from app.core.db import SessionLocal, engine
from app.models import (
    AuditLog, BagSupplier, BagSupply, Bilty, Broker, Commencing, Farmer, Grain, Industry, LabourGroup, LabourWork, Payment,
    PaymentAllocation, PurchaseEntry, Receipt, ReceiptAllocation, Transporter, Truck, TruckLoadLine, TruckTrip, User,
)
from app.services import audit
from app.services import payables as pay_svc
from app.services import receivables as rec_svc
from app.services.money import payable_amount
from app.services.years import business_year_of

IDS_FILE = Path(__file__).with_name(".demo_ids.json")
N = 10
rng = random.Random(2026)
TODAY = date.today()

# ------------------------------------------------------------------ master data
VILLAGES = [("Vanthali", "વંથલી"), ("Mendarda", "મેંદરડા"), ("Bhesan", "ભેસાણ")]
FARMERS = [
    ("Patel Ramesh Bhimjibhai", "પટેલ રમેશ ભીમજીભાઈ"), ("Vaghasiya Dinesh Karsanbhai", "વઘાસીયા દિનેશ કરસનભાઈ"),
    ("Kotadiya Mansukh Jerambhai", "કોટડીયા મનસુખ જેરામભાઈ"), ("Sorathiya Bharat Devjibhai", "સોરઠીયા ભરત દેવજીભાઈ"),
    ("Dobariya Hasmukh Lakhabhai", "ડોબરીયા હસમુખ લખાભાઈ"), ("Kakadiya Pravin Ratilal", "કાકડીયા પ્રવીણ રતિલાલ"),
    ("Gajera Nilesh Mohanbhai", "ગજેરા નિલેશ મોહનભાઈ"), ("Rupareliya Jayesh Becharbhai", "રૂપારેલીયા જયેશ બેચરભાઈ"),
    ("Vekariya Ashok Gordhanbhai", "વેકરીયા અશોક ગોરધનભાઈ"), ("Bhalala Kishor Nathabhai", "ભાલાળા કિશોર નાથાભાઈ"),
]
BAG_SUPPLIERS = [("Shyam Bags", "Mavani Shyamji Kanjibhai"), ("Krishna Packaging", "Radadiya Krishna Hirjibhai"), ("Jay Ambe Bags", "Thakkar Jayesh Ambalal"),
                 ("Ganesh Sacks", "Sheth Ganesh Harilal"), ("Khodiyar Bag House", "Bhut Jagdish Khodabhai"), ("Sardar Plastics", "Patel Sardar Vallabhbhai"),
                 ("Maruti Bags", "Gadhiya Maruti Nandan"), ("Om Packaging", "Joshi Omprakash Mohanlal"), ("Bhavani Sacks", "Dave Bhavan Shankarlal"), ("Umiya Bags", "Kanani Umiyashankar Bhikhabhai")]
LABOUR = [("Hanuman Group", "હનુમાન ગ્રુપ", "Parmar Lakha Hirabhai"), ("Jay Dwarkadhish", "જય દ્વારકાધીશ", "Solanki Vijay Raghabhai"), ("Ramapir Group", "રામાપીર ગ્રુપ", "Chavda Ramesh Devabhai"),
          ("Khodiyar Mandal", "ખોડિયાર મંડળ", "Rathod Kanu Bhikhabhai"), ("Ambaji Group", "અંબાજી ગ્રુપ", "Makwana Ambaram Jivabhai"), ("Jalaram Group", "જલારામ ગ્રુપ", "Sondarva Jalu Karshanbhai"),
          ("Sai Group", "સાઈ ગ્રુપ", "Vala Sagar Mepabhai"), ("Shivshakti Group", "શિવશક્તિ ગ્રુપ", "Zala Shiva Jagabhai"), ("Mahakali Group", "મહાકાળી ગ્રુપ", "Bamaniya Kali Nathabhai"), ("Bajrang Group", "બજરંગ ગ્રુપ", "Gohil Bajrang Ramabhai")]
TRANSPORTERS = [("Shree Ganesh Transport", "Ganesh", "Rajkot"), ("Jay Bhavani Roadways", "Bhavani", "Junagadh"), ("Saurashtra Carriers", "Saurashtra", "Gondal"), ("Patel Logistics", "Patel Logi", "Morbi"),
                ("Maa Karni Transport", "Karni", "Jetpur"), ("Khodal Freight", "Khodal", "Upleta"), ("Sorath Roadlines", "Sorath", "Keshod"), ("New Gujarat Cargo", "NG Cargo", "Jamnagar"),
                ("Dwarka Transport Co", "Dwarka TC", "Dhoraji"), ("Ramdev Transport", "Ramdev", "Rajkot")]
TRUCKS = ["GJ11AB1234", "GJ03BT4521", "GJ14X6720", "GJ01DZ3345", "GJ03AX9081", "GJ11BC2277", "GJ10TT5566", "GJ03CD7410", "GJ13AA8802", "GJ05YZ1969"]
INDUSTRIES = [("Shree Balaji Rice Mill", "શ્રી બાલાજી રાઈસ મિલ", "Rice", "Morbi"), ("Khodal Oil Mill", "ખોડલ ઓઈલ મિલ", "Groundnut oil", "Gondal"),
              ("Annapurna Flour Mill", "અન્નપૂર્ણા ફ્લોર મિલ", "Wheat flour", "Rajkot"), ("Gujarat Dal Mill", "ગુજરાત દાલ મિલ", "Dal", "Jetpur"), ("Saurashtra Agro", "સૌરાષ્ટ્ર એગ્રો", "Castor oil", "Jamnagar"),
              ("Sorath Foods", "સોરઠ ફૂડ્સ", "Besan", "Junagadh"), ("Madhav Agro Industries", "માધવ એગ્રો ઇન્ડસ્ટ્રીઝ", "Pulses", "Dhoraji"), ("Jay Jalaram Mill", "જય જલારામ મિલ", "Rice", "Upleta"),
              ("Shakti Oil Industries", "શક્તિ ઓઈલ ઇન્ડસ્ટ્રીઝ", "Sesame oil", "Keshod"), ("Vraj Agro Products", "વ્રજ એગ્રો પ્રોડક્ટ્સ", "Spices", "Unjha")]
BROKERS = [("Joshi Dhirubhai", "ધીરુભાઈ જોશી"), ("Thakkar Rasiklal", "રસિકલાલ ઠક્કર"), ("Mehta Jitendra", "જીતેન્દ્ર મહેતા"), ("Patel Sureshbhai", "સુરેશભાઈ પટેલ"), ("Vyas Hasmukh", "હસમુખ વ્યાસ"),
           ("Dave Kantilal", "કાંતિલાલ દવે"), ("Trivedi Mahesh", "મહેશ ત્રિવેદી"), ("Bhatt Pravinbhai", "પ્રવીણભાઈ ભટ્ટ"), ("Shah Narendra", "નરેન્દ્ર શાહ"), ("Pandya Girish", "ગિરીશ પંડ્યા")]
# name, gujarati, net bag kg, rate per 20 kg, default terms
GRAINS = [("Wheat", "ઘઉં", 50, 520, "clean, variety"), ("Paddy", "ડાંગર", 50, 410, "clean, dust, harvester"), ("Groundnut", "મગફળી", 35, 1150, "clean, moisture, clay"),
          ("Chickpea", "ચણા", 50, 1080, "clean, green, variety"), ("Pigeon pea", "તુવેર", 50, 1320, "clean, variety"), ("Mung", "મગ", 50, 1480, "clean, moisture"),
          ("Sesame", "તલ", 70, 2100, "clean, moisture, oil content"), ("Castor", "એરંડા", 70, 1190, "clean, moisture"), ("Cumin", "જીરું", 35, 4300, "clean, dust, variety"), ("Soybean", "સોયાબીન", 100, 900, "clean, moisture")]


def mobile(block: int, i: int) -> str:
    return f"9{block:03d}0{i + 1:05d}"  # 9BBB0NNNNN -> unique per table block, 10 digits


def stamp(db, user, table, obj, changes=None):
    audit.log(db, user, "create", table, obj.id, changes or {"demo": True})


async def seed() -> None:
    if IDS_FILE.exists():
        sys.exit(f"Demo data already seeded ({IDS_FILE.name} exists). Run with --remove first.")
    ids: dict[str, list[int]] = {}
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.role == "owner").order_by(User.id))
        if user is None:
            sys.exit("Create an owner user first (scripts.create_user).")

        # ---- masters
        farmers = [Farmer(name=n, name_gu=g, mobile=mobile(1, i), village=VILLAGES[i % 3][0], village_gu=VILLAGES[i % 3][1],
                          head_of_family=(FARMERS[(i + 3) % N][0] if i % 4 == 0 else None), upi_number=mobile(1, i) if i % 2 == 0 else None,
                          house=f"Near {['school', 'temple', 'panchayat', 'water tank'][i % 4]}", bank_name="State Bank of India" if i % 3 == 0 else None)
                   for i, (n, g) in enumerate(FARMERS)]
        suppliers = [BagSupplier(name=o, pet_name=p, mobile=mobile(2, i), upi_number=mobile(2, i)) for i, (p, o) in enumerate(BAG_SUPPLIERS)]
        labour = [LabourGroup(name=ld, mobile=mobile(3, i), group_name=gn, group_name_gu=gg) for i, (gn, gg, ld) in enumerate(LABOUR)]
        transporters = [Transporter(name=n, pet_name=p, location=loc, owner_name=f"{p} Owner", mobile=mobile(4, i)) for i, (n, p, loc) in enumerate(TRANSPORTERS)]
        trucks = [Truck(truck_number=tn, owner_name=f"{TRANSPORTERS[i][1]} Owner", owner_mobile=mobile(5, i), driver_name=f"Driver {i + 1} {['Ahir', 'Rabari', 'Kathi', 'Bharwad'][i % 4]}",
                        driver_mobile=mobile(6, i)) for i, tn in enumerate(TRUCKS)]
        industries = [Industry(name=n, name_gu=g, owner_name=f"{n.split()[0]} Owner", owner_mobile=mobile(7, i), supervisor_name=f"Supervisor {i + 1}", supervisor_mobile=mobile(8, i),
                               product=p, location=loc, required_quality="FAQ grade, moisture below 12%") for i, (n, g, p, loc) in enumerate(INDUSTRIES)]
        brokers = [Broker(name=n, name_gu=g, mobile=mobile(9, i), brokerage_per_truck=1000 + 100 * (i % 6) * 2, upi_number=mobile(9, i)) for i, (n, g) in enumerate(BROKERS)]
        grains = [Grain(name=n, name_gu=g, default_net_weight=w, default_terms=t) for n, g, w, _, t in GRAINS]
        masters = dict(farmers=farmers, bag_suppliers=suppliers, labour_groups=labour, transporters=transporters, trucks=trucks, industries=industries, brokers=brokers, grains=grains)
        for rows in masters.values():
            db.add_all(rows)
        await db.flush()
        for name, rows in masters.items():
            ids[name] = [r.id for r in rows]

        # ---- commencings: one village deal per grain
        day = lambda back: TODAY - timedelta(days=back)  # noqa: E731
        commencings = []
        for i, g in enumerate(grains):
            c = Commencing(business_year=business_year_of(day(5 - i % 5)), commencing_date=day(5 - i % 5), village=VILLAGES[i % 3][0], grain_id=g.id,
                           rate_per_20kg=GRAINS[i][3], net_weight=g.default_net_weight, pay_after_days=[7, 10, 15, 20][i % 4], terms=g.default_terms,
                           description="Demo commencing", created_by=user.id)
            commencings.append(c)
        db.add_all(commencings)
        await db.flush()
        ids["commencings"] = [c.id for c in commencings]
        for c in commencings:
            stamp(db, user, "commencings", c)

        # ---- farmer weighing entries: one per commencing
        entries = []
        for i, c in enumerate(commencings):
            bags, kilos = rng.randint(120, 400), rng.choice([0, 0, rng.randint(5, c.net_weight - 1)])
            amount = payable_amount(bags, kilos, c.net_weight, c.rate_per_20kg)
            borrowing = rng.choice([0, 0, 500, 1000, 2000]) if amount > 3000 else 0
            entries.append(PurchaseEntry(
                commencing_id=c.id, farmer_id=farmers[i].id, labour_group_id=labour[i].id, entry_date=c.commencing_date, filled_bags=bags, extra_kilos=kilos,
                raw_weight=bags * c.net_weight + kilos + rng.randint(20, 90), payable_amount=amount, borrowing=borrowing,
                due_date=c.commencing_date + timedelta(days=c.pay_after_days), description=rng.choice([None, None, "2 quality grains", "warning: moisture"]), created_by=user.id))
        db.add_all(entries)
        await db.flush()
        ids["purchase_entries"] = [e.id for e in entries]
        for e in entries:
            stamp(db, user, "purchase_entries", e)

        # ---- truck trips: each loads 80% of its commencing's bags
        trips, lines = [], []
        for i, c in enumerate(commencings):
            d = day(3 - i % 3)
            trips.append(TruckTrip(business_year=business_year_of(d), trip_date=d, truck_id=trucks[i].id, transport_id=transporters[i].id, labour_group_id=labour[(i + 1) % N].id,
                                   industry_id=industries[i % 5].id, grain_id=c.grain_id, rent_per_ton=rng.randrange(700, 1300, 50), rent_per_bag=rng.randint(15, 30),
                                   advance_amount=rng.choice([0, 500, 1000, 2000]), other_deduction=0, description="Demo trip", created_by=user.id))
        db.add_all(trips)
        await db.flush()
        for i, t in enumerate(trips):
            lines.append(TruckLoadLine(trip_id=t.id, commencing_id=commencings[i].id, bags=int(entries[i].filled_bags * 0.8)))
        db.add_all(lines)
        await db.flush()
        ids["truck_trips"], ids["truck_load_lines"] = [t.id for t in trips], [ln.id for ln in lines]
        for t in trips:
            stamp(db, user, "truck_trips", t)

        # ---- bilty: 7 weighed by the industry, 3 still awaiting the industry weight
        bilties = []
        for i, t in enumerate(trips):
            c, bags = commencings[i], lines[i].bags
            m_net = bags * c.net_weight + rng.randint(0, 40)
            m_tare = rng.randrange(9000, 11000, 10)
            i_net = i_tare = None
            if i < 7:
                i_net = m_net - int(m_net * rng.uniform(0.0, 0.008))
                i_tare = m_tare + rng.randint(-20, 20)
            bilties.append(Bilty(
                trip_id=t.id, business_year=t.business_year, bilty_date=t.trip_date, bill_number=201 + i, broker_id=brokers[i].id,
                grain_rate=-(-int(c.rate_per_20kg * 1.08) // 10) * 10, rate_unit_kg=20, rate_change=rng.choice([0, 0, 0, 5]), brokerage_amount=brokers[i].brokerage_per_truck,
                merchant_total_weight=m_net + m_tare, merchant_tare_weight=m_tare,
                industry_total_weight=None if i_net is None else i_net + i_tare, industry_tare_weight=i_tare,
                description="Demo bilty" if i < 7 else "Demo bilty - industry weight awaited", created_by=user.id))
        db.add_all(bilties)
        await db.flush()
        ids["bilties"] = [b.id for b in bilties]
        for b in bilties:
            stamp(db, user, "bilties", b)

        # ---- labour work and bag supplies
        work = []
        for i in range(N):
            wages = rng.randrange(3000, 9000, 100)
            borrow = rng.choice([0, 0, 500, 1000])
            work.append(LabourWork(labour_group_id=labour[i].id, work_date=day(5 - i % 5), business_year=business_year_of(day(5 - i % 5)), payable_amount=wages,
                                   borrowing_amount=min(borrow, wages), petrol=rng.choice([0, 200, 300, 500]), meal=rng.choice([0, 150, 250]), description="Demo labour work", created_by=user.id))
        bags = [BagSupply(supplier_id=suppliers[i].id, farmer_id=farmers[i].id, supply_date=day(6), business_year=business_year_of(day(6)), rate=rng.randint(12, 25),
                          units=rng.randrange(200, 600, 50), description="Demo bag supply", created_by=user.id) for i in range(N)]
        for b in bags:
            b.payable_amount = b.rate * b.units
        db.add_all(work + bags)
        await db.flush()
        ids["labour_work"], ids["bag_supplies"] = [w.id for w in work], [b.id for b in bags]
        for w in work:
            stamp(db, user, "labour_work", w)
        for b in bags:
            stamp(db, user, "bag_supplies", b)
        await db.commit()

        # ---- receipts (money in): partial, oldest weighed bilty first, spread over the industries
        receipt_ids, k = [], 0
        methods = [("bank", "UTR"), ("upi", "UPI"), ("cheque", "CHQ")]
        while len(receipt_ids) < N and k < 40:
            views = [v for v in await rec_svc.bilty_views(db) if v.due and v.due > 0]
            if not views:
                break
            v = views[k % len(views)]
            ind = v.bilty.trip.industry
            due = sum(x.due for x in views if x.bilty.trip.industry_id == ind.id)
            amount = min(due, max(10000, round(due * rng.choice([0.25, 0.4, 0.5]), -3)))
            method, tag = methods[k % 3]
            r = await rec_svc.record_receipt(db, user, ind.id, dict(
                receipt_date=day(rng.randint(0, 2)), amount=amount, method=method, reference_no=None if method == "cash" else f"{tag}{rng.randint(100000, 999999)}",
                payer_name=ind.owner_name, note="Demo receipt"))
            await db.commit()
            receipt_ids.append(r.id)
            k += 1
        ids["receipts"] = receipt_ids

        # ---- payments (money out): 4 farmers, 3 transporters, 1 broker, 1 labour, 1 bag supplier
        plan = [("farmer", farmers[i].id) for i in range(4)] + [("transporter", transporters[i].id) for i in (0, 1, 2)] + \
               [("broker", brokers[0].id), ("labour", labour[0].id), ("bag_supplier", suppliers[0].id)]
        payment_ids = []
        for n, (ptype, pid) in enumerate(plan):
            rows = [p for p in await pay_svc.load_payables(db, ptype, pid) if p.due > 0]
            if not rows:
                continue
            due = sum(p.due for p in rows)
            amount = min(due, max(500, round(due * rng.choice([0.3, 0.5, 0.6]), -2)))
            party = await pay_svc.get_party(db, ptype, pid)
            rname, rmobile = pay_svc.PARTIES[ptype].receiver(party)
            method = ["cash", "upi", "bank"][n % 3]
            p = await pay_svc.record_payment(db, user, ptype, pid, dict(
                payment_date=day(rng.randint(0, 2)), amount=amount, method=method, receiver_name=rname, receiver_mobile=rmobile,
                reference_no=None if method == "cash" else f"REF{rng.randint(100000, 999999)}", note="Demo payment"))
            await db.commit()
            payment_ids.append(p.id)
        ids["payments"] = payment_ids

    IDS_FILE.write_text(json.dumps(ids, indent=1))
    await engine.dispose()
    print("Inserted demo data:")
    for name, v in ids.items():
        print(f"  {name:18} {len(v)}")


async def remove() -> None:
    if not IDS_FILE.exists():
        sys.exit("No demo data recorded (nothing to remove).")
    ids = json.loads(IDS_FILE.read_text())
    async with SessionLocal() as db:
        pay_ids, rec_ids = ids.get("payments", []), ids.get("receipts", [])
        await db.execute(delete(PaymentAllocation).where(PaymentAllocation.payment_id.in_(pay_ids)))
        await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
        await db.execute(delete(ReceiptAllocation).where(ReceiptAllocation.receipt_id.in_(rec_ids)))
        await db.execute(delete(Receipt).where(Receipt.id.in_(rec_ids)))
        for model, key in ((Bilty, "bilties"), (TruckLoadLine, "truck_load_lines"), (TruckTrip, "truck_trips"), (BagSupply, "bag_supplies"), (LabourWork, "labour_work"),
                           (PurchaseEntry, "purchase_entries"), (Commencing, "commencings"), (Farmer, "farmers"), (BagSupplier, "bag_suppliers"), (LabourGroup, "labour_groups"),
                           (Transporter, "transporters"), (Truck, "trucks"), (Industry, "industries"), (Broker, "brokers"), (Grain, "grains")):
            await db.execute(delete(model).where(model.id.in_(ids.get(key, []))))
        for table, key in (("commencings", "commencings"), ("purchase_entries", "purchase_entries"), ("truck_trips", "truck_trips"), ("bilties", "bilties"),
                           ("labour_work", "labour_work"), ("bag_supplies", "bag_supplies"), ("payments", "payments"), ("receipts", "receipts")):
            await db.execute(delete(AuditLog).where(AuditLog.table_name == table, AuditLog.record_id.in_(ids.get(key, []))))
        await db.commit()
    IDS_FILE.unlink()
    await engine.dispose()
    print("Demo data removed.")


if __name__ == "__main__":
    asyncio.run(remove() if "--remove" in sys.argv else seed())
