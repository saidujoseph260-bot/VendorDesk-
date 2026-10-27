import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'vendordesk-super-secret-key-2026')

# Initialize Supabase
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
PDF_DIR = 'static'
if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)


def get_current_vendor():
    vendor_id = session.get('vendor_id')
    if not vendor_id:
        return None
    res = supabase.table('vendors').select('*').eq('id', vendor_id).execute()
    return res.data[0] if res.data else None


@app.route('/')
def home():
    vendor = get_current_vendor()
    if not vendor:
        return render_template('index.html', vendor=None)

    # Date Filter Parameters
    time_filter = request.args.get('filter', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Query receipts for this vendor
    query = supabase.table('receipts').select('*').eq('vendor_id', vendor['id'])

    now = datetime.utcnow()
    if time_filter == 'today':
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        query = query.gte('date', today_start)
    elif time_filter == 'week':
        week_start = (now - timedelta(days=7)).isoformat()
        query = query.gte('date', week_start)
    elif time_filter == 'month':
        month_start = (now - timedelta(days=30)).isoformat()
        query = query.gte('date', month_start)
    elif time_filter == 'year':
        year_start = (now - timedelta(days=365)).isoformat()
        query = query.gte('date', year_start)
    elif time_filter == 'custom' and start_date and end_date:
        query = query.gte('date', f"{start_date}T00:00:00").lte('date', f"{end_date}T23:59:59")

    res = query.order('id', desc=True).execute()
    receipts = res.data if res.data else []

    # Calculate Revenue and Invoice Count
    total_revenue = sum(float(r['amount']) for r in receipts if r.get('status') == 'paid')
    total_invoices = len(receipts)

    return render_template(
        'index.html',
        vendor=vendor,
        revenue=total_revenue,
        invoices=total_invoices,
        receipts=receipts,
        current_filter=time_filter,
        start_date=start_date,
        end_date=end_date
    )


@app.route('/register', methods=['POST'])
def register():
    data = request.form
    email = data.get('email').lower().strip()
    password = data.get('password')
    business_name = data.get('business_name')
    phone = data.get('phone')
    ig_handle = data.get('ig_handle')
    bank_details = data.get('bank_details')

    # Check if vendor exists
    existing = supabase.table('vendors').select('id').eq('email', email).execute()
    if existing.data:
        return jsonify({"error": "Email already registered."}), 400

    hashed_pw = generate_password_hash(password)
    new_vendor = {
        "email": email,
        "password_hash": hashed_pw,
        "business_name": business_name,
        "phone": phone,
        "ig_handle": ig_handle,
        "bank_details": bank_details
    }

    res = supabase.table('vendors').insert(new_vendor).execute()
    if res.data:
        session['vendor_id'] = res.data[0]['id']
        return jsonify({"status": "success"})
    return jsonify({"error": "Failed to create account."}), 500


@app.route('/login', methods=['POST'])
def login():
    data = request.form
    email = data.get('email').lower().strip()
    password = data.get('password')

    res = supabase.table('vendors').select('*').eq('email', email).execute()
    if not res.data:
        return jsonify({"error": "Invalid email or password."}), 400

    vendor = res.data[0]
    if check_password_hash(vendor['password_hash'], password):
        session['vendor_id'] = vendor['id']
        return jsonify({"status": "success"})
    return jsonify({"error": "Invalid email or password."}), 400


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/update-profile', methods=['POST'])
def update_profile():
    vendor = get_current_vendor()
    if not vendor:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    update_data = {
        "business_name": data.get('business_name'),
        "phone": data.get('phone'),
        "ig_handle": data.get('ig_handle'),
        "bank_details": data.get('bank_details')
    }

    supabase.table('vendors').update(update_data).eq('id', vendor['id']).execute()
    return jsonify({"status": "success"})


@app.route('/add-receipt', methods=['POST'])
def add_receipt():
    vendor = get_current_vendor()
    if not vendor:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    new_receipt = {
        "vendor_id": vendor['id'],
        "customer_name": data.get('name'),
        "amount": float(data.get('amount')),
        "item_desc": data.get('desc'),
        "status": data.get('status', 'paid')
    }

    res = supabase.table('receipts').insert(new_receipt).execute()
    if res.data:
        return jsonify({"status": "success"})
    return jsonify({"error": "Failed to save receipt"}), 500


@app.route('/mark-paid/<int:receipt_id>', methods=['POST'])
def mark_paid(receipt_id):
    vendor = get_current_vendor()
    if not vendor:
        return jsonify({"error": "Unauthorized"}), 401

    supabase.table('receipts').update({'status': 'paid'}).eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
    return jsonify({"status": "success"})


@app.route('/receipt/<int:receipt_id>')
def get_receipt(receipt_id):
    vendor = get_current_vendor()
    if not vendor:
        return jsonify({"error": "Unauthorized"}), 401

    res = supabase.table('receipts').select('*').eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
    if res.data:
        r = res.data[0]
        return jsonify({
            "id": r['id'],
            "name": r['customer_name'],
            "amount": float(r['amount']),
            "desc": r['item_desc'],
            "status": r['status'],
            "date": r['date'][:10],
            "business_name": vendor['business_name'],
            "phone": vendor['phone'],
            "ig_handle": vendor['ig_handle'],
            "bank_details": vendor['bank_details']
        })
    return jsonify({"error": "Not found"}), 404


@app.route('/download-pdf/<int:receipt_id>')
def download_pdf(receipt_id):
    vendor = get_current_vendor()
    if not vendor:
        return "Unauthorized", 401

    res = supabase.table('receipts').select('*').eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
    if not res.data:
        return "Receipt not found", 404

    row = res.data[0]
    pdf_filename = f"receipt_{receipt_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)

    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>{vendor['business_name'].upper()}</b>", styles['Title']))
    story.append(Paragraph(f"Phone: {vendor.get('phone', '')} | IG: {vendor.get('ig_handle', '')}", styles['Normal']))
    story.append(Spacer(1, 15))
    story.append(Paragraph(f"<b>OFFICIAL INVOICE #{row['id']}</b>", styles['Heading2']))
    story.append(Paragraph(f"<b>Status:</b> {row['status'].upper()}", styles['Normal']))
    story.append(Paragraph(f"<b>Date:</b> {row['date'][:10]}", styles['Normal']))
    story.append(Paragraph(f"<b>Customer Name:</b> {row['customer_name']}", styles['Normal']))
    story.append(Paragraph(f"<b>Item Description:</b> {row['item_desc']}", styles['Normal']))
    story.append(Paragraph(f"<b>Amount Paid:</b> NGN {float(row['amount']):,.2f}", styles['Heading1']))
    if vendor.get('bank_details'):
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"<b>Bank Details:</b> {vendor['bank_details']}", styles['Normal']))
    story.append(Spacer(1, 20))
    story.append(Paragraph("<i>Thank you for your patronage! Verified by VendorDesk.</i>", styles['Italic']))

    doc.build(story)
    return send_file(pdf_path, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
