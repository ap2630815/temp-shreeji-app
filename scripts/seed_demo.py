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
    AuditLog, BagSupplier, BagSupply, Bilty, Broker, BrokerBooking, Brokerage, PurchaseIndividual, Farmer, Grain, Industry, Labour, LabourGroup, LabourGroupWage,
    LabourWork, Payment, PaymentAllocation, PurchaseFarmerEntry, PurchaseGroup, PurchaseGroupFarmer, Receipt, ReceiptAllocation, Transporter, Truck, TruckLoadLine,
    TruckTrip, User, Village,
)
from app.services import audit
from app.services import payables as pay_svc
from app.services import receivables as rec_svc
from app.services.money import payable_amount, total_available_bags
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
        villages = [Village(village_name=n, village_name_gu=g) for n, g in VILLAGES]
        grains = [Grain(grain_name=n, grain_name_gu=g, net_bag_weight=w, booking_weight=20 if i % 3 else 100, grain_terms=t) for i, (n, g, w, _, t) in enumerate(GRAINS)]
        labour = [LabourGroup(group_name=gn, group_name_gu=gg) for gn, gg, _ in LABOUR]
        db.add_all(villages + grains + labour)
        await db.flush()
        farmers = [Farmer(farmer_name=n, farmer_name_gu=g, mobile=mobile(1, i), village_id=villages[i % 3].id,
                          head_of_family=(FARMERS[(i + 3) % N][0] if i % 4 == 0 else None), upi_number=mobile(1, i) if i % 2 == 0 else None,
                          house=f"Near {['school', 'temple', 'panchayat', 'water tank'][i % 4]}", bank_name="State Bank of India" if i % 3 == 0 else None)
                   for i, (n, g) in enumerate(FARMERS)]
        suppliers = [BagSupplier(name=o, pet_name=p, mobile=mobile(2, i), upi_number=mobile(2, i)) for i, (p, o) in enumerate(BAG_SUPPLIERS)]
        transporters = [Transporter(transporter_name=n, pet_name=p, location=loc, owner_name=f"{p} Owner", mobile=mobile(4, i)) for i, (n, p, loc) in enumerate(TRANSPORTERS)]
        trucks = [Truck(truck_number=tn, truck_owner_name=f"{TRANSPORTERS[i][1]} Owner", truck_owner_mobile=mobile(5, i), driver_name=f"Driver {i + 1} {['Ahir', 'Rabari', 'Kathi', 'Bharwad'][i % 4]}",
                        driver_mobile=mobile(6, i)) for i, tn in enumerate(TRUCKS)]
        industries = [Industry(industrialist_name=n, industrialist_name_gu=g, owner_name=f"{n.split()[0]} Owner", owner_mobile=mobile(7, i), supervisor_name=f"Supervisor {i + 1}",
                               supervisor_mobile=mobile(8, i), grain=p, location=loc, quality_expectation="FAQ grade, moisture below 12%") for i, (n, g, p, loc) in enumerate(INDUSTRIES)]
        brokers = [Broker(broker_name=n, broker_name_gu=g, mobile=mobile(9, i), upi_number=mobile(9, i)) for i, (n, g) in enumerate(BROKERS)]
        db.add_all(farmers + suppliers + transporters + trucks + industries + brokers)
        await db.flush()
        labours = [Labour(labour_name=ld, labour_group_id=labour[i].id, mobile=mobile(3, i)) for i, (_, _, ld) in enumerate(LABOUR)]
        brokerages = [Brokerage(broker_id=brokers[i].id, grain_id=grains[i].id, brokerage_per_bag=rng.randint(2, 8), description="Demo brokerage") for i in range(N)]
        wages = [LabourGroupWage(labour_group_id=labour[i].id, grain_id=grains[i].id, weighing_rate=rng.randint(1, 3), loading_rate=rng.randint(2, 5),
                                 pulling_rate=rng.randint(1, 4), mixing_rate=rng.randint(1, 3), other_expenses=rng.choice([None, 0, 200]), description="Demo wages") for i in range(N)]
        db.add_all(labours + brokerages + wages)
        await db.flush()
        masters = dict(villages=villages, grains=grains, labour_groups=labour, farmers=farmers, bag_suppliers=suppliers, transporters=transporters, trucks=trucks,
                       industries=industries, brokers=brokers, labours=labours, brokerages=brokerages, labour_group_wages=wages)
        for name, rows in masters.items():
            ids[name] = [r.id for r in rows]

        # ---- purchase_group: one deal per grain (a village can have several)
        day = lambda back: TODAY - timedelta(days=back)  # noqa: E731
        infos = []
        for i, g in enumerate(grains):
            d = day(5 - i % 5)
            infos.append(PurchaseGroup(purchase_group_date=d, business_year=business_year_of(d), village_id=villages[i % 3].id, grain_id=g.id, grain_rate_per_20kg=GRAINS[i][3],
                                      pay_after_no_of_days=[7, 10, 15, 20][i % 4], purchase_group_terms=g.grain_terms, description="Demo purchase", created_by=user.id))
        db.add_all(infos)
        await db.flush()
        ids["purchase_group"] = [p.id for p in infos]
        for p in infos:
            stamp(db, user, "purchase_group", p)

        # ---- the farmers who joined each purchase: the one with an entry plus two more who have not delivered yet
        joined = [PurchaseGroupFarmer(purchase_group_id=p.id, farmer_id=farmers[(i + k) % N].id, created_by=user.id) for i, p in enumerate(infos) for k in (0, 1, 2)]
        db.add_all(joined)
        await db.flush()
        ids["purchase_group_farmers"] = [j.id for j in joined]

        # ---- farmer weighing entries: one per purchase_group (for the first listed farmer)
        entries = []
        for i, p in enumerate(infos):
            net = grains[i].net_bag_weight
            bags, kilos, handful = rng.randint(120, 400), rng.choice([0, 0, rng.randint(5, net - 1)]), rng.choice([0, 0, 3, 5])
            amount = payable_amount(bags, kilos, net, p.grain_rate_per_20kg)
            borrowing = rng.choice([0, 0, 500, 1000, 2000]) if amount > 3000 else 0
            entries.append(PurchaseFarmerEntry(
                purchase_entry_date=p.purchase_group_date, business_year=p.business_year, purchase_group_id=p.id, farmer_id=farmers[i].id, labour_group_id=labour[i].id,
                no_of_filled_bags=bags, extra_kilos=kilos, no_of_handful_bags=handful, total_available_bags=total_available_bags(bags, handful),
                payable_amount=amount, borrowed_amount=borrowing, due_date=p.purchase_group_date + timedelta(days=p.pay_after_no_of_days),
                expected_raw_weight_per_bag=net + rng.randint(0, 2), grain_quality_code=rng.choice([None, "A", "B"]), grain_store_at=rng.choice([None, "Farmer's shed", "Godown"]),
                description=rng.choice([None, None, "2 quality grains", "warning: moisture"]), created_by=user.id))
        db.add_all(entries)
        await db.flush()
        ids["purchase_farmers_entries"] = [e.id for e in entries]
        for e in entries:
            stamp(db, user, "purchase_farmers_entries", e)

        # ---- two direct entries (the one-form Purchase Individual): purchase and entry columns in one flat row, one description
        direct = []
        for k, (gi, fi, bags_d) in enumerate([(0, 8, 60), (2, 9, 45)]):
            g, d = grains[gi], day(2 - k)
            rate = GRAINS[gi][3]
            direct.append(PurchaseIndividual(
                purchase_individual_date=d, business_year=business_year_of(d), village_id=farmers[fi].village_id, grain_id=g.id, grain_rate_per_20kg=rate, pay_after_no_of_days=7,
                terms=g.grain_terms, farmer_id=farmers[fi].id, labour_group_id=labour[fi].id, no_of_filled_bags=bags_d, extra_kilos=0, no_of_handful_bags=0,
                total_available_bags=bags_d, payable_amount=payable_amount(bags_d, 0, g.net_bag_weight, rate), borrowed_amount=0, due_date=d + timedelta(days=7),
                description="Demo direct entry", created_by=user.id))
        db.add_all(direct)
        await db.flush()
        ids["purchase_individuals"] = [x.id for x in direct]
        for x in direct:
            stamp(db, user, "purchase_individuals", x)


        # ---- broker bookings: one per brokerage, each for one of the first 5 industries
        bookings = []
        for i, br in enumerate(brokerages):
            d = day(4 - i % 4)
            bookings.append(BrokerBooking(booking_date=d, business_year=business_year_of(d), brokerage_id=br.id, industry_id=industries[i % 5].id,
                                          grain_rate_per_booking_weight=-(-int(GRAINS[i][3] * 1.08) // 10) * 10 * (5 if grains[i].booking_weight == 100 else 1),
                                          truck_size=[10, 15, 20, 25, 30][i % 5], percentage_deduction=rng.choice([None, 0.5, 1, 2]), description="Demo booking", created_by=user.id))
        db.add_all(bookings)
        await db.flush()
        ids["broker_bookings"] = [b.id for b in bookings]
        for b in bookings:
            stamp(db, user, "broker_bookings", b)

        # ---- truck trips: one per booking, each loads 80% of the entry of the same grain
        trips, lines = [], []
        for i, bk in enumerate(bookings):
            d = day(3 - i % 3)
            per_ton = i % 2 == 0
            trips.append(TruckTrip(trip_date=d, business_year=business_year_of(d), broker_booking_id=bk.id, truck_id=trucks[i].id, transporter_id=transporters[i].id,
                                   labour_group_id=labour[(i + 1) % N].id, rent_per_ton=rng.randrange(700, 1300, 50) if per_ton else 0,
                                   rent_per_bag=0 if per_ton else rng.randint(15, 30), advance_amount=rng.choice([0, 500, 1000, 2000]),
                                   other_payable=rng.choice([0, 0, 300]), other_deduction=0, description="Demo trip", created_by=user.id))
        db.add_all(trips)
        await db.flush()
        for i, t in enumerate(trips):
            bags = int(entries[i].total_available_bags * 0.8)
            lines.append(TruckLoadLine(trip_id=t.id, purchase_farmer_entry_id=entries[i].id, no_of_loaded_bags=bags, total_remaining_bags=entries[i].total_available_bags - bags))
        db.add_all(lines)
        await db.flush()
        ids["truck_trips"], ids["truck_load_lines"] = [t.id for t in trips], [ln.id for ln in lines]
        for t in trips:
            stamp(db, user, "truck_trips", t)

        # ---- bilty: 7 weighed by the industry, 3 still awaiting the industry weight
        bilties = []
        for i, t in enumerate(trips):
            bags = lines[i].no_of_loaded_bags
            m_net = bags * grains[i].net_bag_weight + rng.randint(0, 40)
            m_tare = rng.randrange(9000, 11000, 10)
            i_net = i_tare = None
            if i < 7:
                i_net = m_net - int(m_net * rng.uniform(0.0, 0.008))
                i_tare = m_tare + rng.randint(-20, 20)
            bilties.append(Bilty(
                truck_trip_id=t.id, business_year=t.business_year, bilty_date=t.trip_date, bill_number=201 + i, total_bags_in_truck=bags, any_rate_change=rng.choice([0, 0, 0, 5]),
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
            w = rng.randrange(3000, 9000, 100)
            borrow = rng.choice([0, 0, 500, 1000])
            work.append(LabourWork(labour_group_id=labour[i].id, work_date=day(5 - i % 5), business_year=business_year_of(day(5 - i % 5)), payable_amount=w,
                                   borrowing_amount=min(borrow, w), petrol=rng.choice([0, 200, 300, 500]), meal=rng.choice([0, 150, 250]), description="Demo labour work", created_by=user.id))
        bags = [BagSupply(supplier_id=suppliers[i].id, farmer_id=farmers[i].id, supply_date=day(6), business_year=business_year_of(day(6)), rate_per_bag=rng.randint(12, 25),
                          no_of_bags=rng.randrange(200, 600, 50), payable_amount=0, description="Demo bag supply", created_by=user.id) for i in range(N)]
        for b in bags:
            b.payable_amount = b.rate_per_bag * b.no_of_bags
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
            due = sum(x.due for x in views if x.bilty.trip.industry.id == ind.id)
            amount = min(due, max(10000, round(due * rng.choice([0.25, 0.4, 0.5]), -3)))
            method, tag = methods[k % 3]
            r = await rec_svc.record_receipt(db, user, ind.id, dict(
                receipt_date=day(rng.randint(0, 2)), amount=amount, method=method, reference_no=None if method == "cash" else f"{tag}{rng.randint(100000, 999999)}",
                payer_name=ind.owner_name, description="Demo receipt"))
            await db.commit()
            receipt_ids.append(r.id)
            k += 1
        ids["receipts"] = receipt_ids

        # ---- payments (money out): 4 farmers, 3 truck owners, 1 broker, 1 labour group, 1 bag supplier
        plan = [("farmer", farmers[i].id) for i in range(4)] + [("truck", trucks[i].id) for i in (0, 1, 2)] + \
               [("broker", brokers[0].id), ("labour_group", labour[0].id), ("bag_supplier", suppliers[0].id)]
        payment_ids = []
        for n, (ptype, pid) in enumerate(plan):
            rows = [p for p in await pay_svc.load_payables(db, ptype, pid) if p.due > 0]
            if not rows:
                continue
            due = sum(p.due for p in rows)
            amount = min(due, max(500, round(due * rng.choice([0.3, 0.5, 0.6]), -2)))
            party = await pay_svc.get_party(db, ptype, pid)
            rname, rmobile = pay_svc.PARTIES[ptype].receiver(party)
            rmobile = rmobile or mobile(3, n)  # labour groups have no mobile of their own
            method = ["cash", "upi", "bank"][n % 3]
            p = await pay_svc.record_payment(db, user, ptype, pid, dict(
                payment_date=day(rng.randint(0, 2)), amount=amount, method=method, receiver_name=rname, receiver_mobile=rmobile,
                reference_no=None if method == "cash" else f"REF{rng.randint(100000, 999999)}", description="Demo payment"))
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
    ids.setdefault("purchase_farmers_entries", ids.get("purchase_farmer_entries", []))  # written before the table was renamed
    ids.setdefault("purchase_farmer_entries", ids["purchase_farmers_entries"])  # old audit rows carry the old table name
    async with SessionLocal() as db:
        pay_ids, rec_ids = ids.get("payments", []), ids.get("receipts", [])
        await db.execute(delete(PaymentAllocation).where(PaymentAllocation.payment_id.in_(pay_ids)))
        await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
        await db.execute(delete(ReceiptAllocation).where(ReceiptAllocation.receipt_id.in_(rec_ids)))
        await db.execute(delete(Receipt).where(Receipt.id.in_(rec_ids)))
        for model, key in ((Bilty, "bilties"), (TruckLoadLine, "truck_load_lines"), (TruckTrip, "truck_trips"), (BrokerBooking, "broker_bookings"),
                           (BagSupply, "bag_supplies"), (LabourWork, "labour_work"), (PurchaseIndividual, "purchase_individuals"), (PurchaseFarmerEntry, "purchase_farmers_entries"), (PurchaseGroupFarmer, "purchase_group_farmers"), (PurchaseGroup, "purchase_group"),
                           (LabourGroupWage, "labour_group_wages"), (Brokerage, "brokerages"), (Labour, "labours"), (Farmer, "farmers"), (BagSupplier, "bag_suppliers"),
                           (LabourGroup, "labour_groups"), (Transporter, "transporters"), (Truck, "trucks"), (Industry, "industries"), (Broker, "brokers"),
                           (Grain, "grains"), (Village, "villages")):
            await db.execute(delete(model).where(model.id.in_(ids.get(key, []))))
        for table in ("purchase_group", "purchase_farmers_entries", "purchase_farmer_entries", "purchase_individuals", "broker_bookings", "truck_trips", "bilties", "labour_work", "bag_supplies", "payments", "receipts"):
            await db.execute(delete(AuditLog).where(AuditLog.table_name == table, AuditLog.record_id.in_(ids.get(table, []))))
        await db.commit()
    IDS_FILE.unlink()
    await engine.dispose()
    print("Demo data removed.")


if __name__ == "__main__":
    asyncio.run(remove() if "--remove" in sys.argv else seed())
