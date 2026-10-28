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

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase Init Error: {e}")

PDF_DIR = 'static'
if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

@app.route('/ping')
def ping():
    return "OK", 200

@app.route('/icon.png')
def serve_icon():
    if os.path.exists('icon.png'):
        return send_file('icon.png')
    elif os.path.exists('static/icon.png'):
        return send_file('static/icon.png')
    return "Icon not found", 404

def get_current_vendor():
    vendor_id = session.get('vendor_id')
    if not vendor_id or not supabase: return None
    try:
        res = supabase.table('vendors').select('*').eq('id', vendor_id).execute()
        return res.data[0] if res.data else None
    except Exception: return None

@app.route('/')
def home():
    vendor = get_current_vendor()
    if not vendor: return render_template('index.html', vendor=None)

    try:
        vid = vendor['id']
        receipts = supabase.table('receipts').select('*').eq('vendor_id', vid).order('id', desc=True).execute().data or []
        expenses = supabase.table('expenses').select('*').eq('vendor_id', vid).order('id', desc=True).execute().data or [] if vendor.get('use_expenses') else []
        inventory = supabase.table('inventory').select('*').eq('vendor_id', vid).order('item_name').execute().data or [] if vendor.get('use_inventory') else []
        customers = supabase.table('customers').select('*').eq('vendor_id', vid).order('name').execute().data or [] if vendor.get('use_crm') else []

        total_revenue = sum(float(r['amount']) for r in receipts if r.get('status') == 'paid')
        total_expenses = sum(float(e['amount']) for e in expenses)
        net_profit = total_revenue - total_expenses
        total_invoices = len(receipts)
    except Exception as e:
        print(f"Home route error: {e}")
        receipts, expenses, inventory, customers = [], [], [], []
        total_revenue, total_expenses, net_profit, total_invoices = 0, 0, 0, 0

    return render_template(
        'index.html', vendor=vendor, revenue=total_revenue, expenses_total=total_expenses,
        net_profit=net_profit, invoices=total_invoices, receipts=receipts,
        expenses=expenses, inventory=inventory, customers=customers
    )

@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.form
        email = data.get('email', '').lower().strip()
        existing = supabase.table('vendors').select('id').eq('email', email).execute()
        if existing.data: return jsonify({"error": "Email already registered."}), 400
        
        new_vendor = {
            "email": email, "password_hash": generate_password_hash(data.get('password')),
            "business_name": data.get('business_name'), "phone": data.get('phone'),
            "ig_handle": data.get('ig_handle'), "bank_details": data.get('bank_details')
        }
        res = supabase.table('vendors').insert(new_vendor).execute()
        if res.data:
            session['vendor_id'] = res.data[0]['id']
            return jsonify({"status": "success"})
        return jsonify({"error": "Failed to create account."}), 500
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        email = request.form.get('email', '').lower().strip()
        res = supabase.table('vendors').select('*').eq('email', email).execute()
        if not res.data: return jsonify({"error": "Account not found."}), 400
        vendor = res.data[0]
        if check_password_hash(vendor['password_hash'], request.form.get('password')):
            session['vendor_id'] = vendor['id']
            return jsonify({"status": "success"})
        return jsonify({"error": "Invalid password."}), 400
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/update-profile', methods=['POST'])
def update_profile():
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        supabase.table('vendors').update({
            "business_name": data.get('business_name'),
            "phone": data.get('phone'),
            "ig_handle": data.get('ig_handle'),
            "bank_details": data.get('bank_details'),
            "use_inventory": data.get('use_inventory', False),
            "use_expenses": data.get('use_expenses', False),
            "use_crm": data.get('use_crm', False)
        }).eq('id', vendor['id']).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/add-receipt', methods=['POST'])
def add_receipt():
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        new_receipt = {
            "vendor_id": vendor['id'], "customer_name": data.get('name'),
            "amount": float(data.get('amount')), "item_desc": data.get('desc'), "status": data.get('status', 'paid')
        }
        res = supabase.table('receipts').insert(new_receipt).execute()
        
        phone = data.get('phone')
        if phone and vendor.get('use_crm'):
            ext = supabase.table('customers').select('*').eq('vendor_id', vendor['id']).eq('phone', phone).execute()
            if not ext.data: supabase.table('customers').insert({"vendor_id": vendor['id'], "name": data.get('name'), "phone": phone}).execute()

        inv_id = data.get('inventory_id')
        if inv_id and vendor.get('use_inventory'):
            item = supabase.table('inventory').select('stock_quantity').eq('id', inv_id).execute()
            if item.data:
                new_qty = max(0, item.data[0]['stock_quantity'] - 1)
                supabase.table('inventory').update({'stock_quantity': new_qty}).eq('id', inv_id).execute()

        return jsonify({"status": "success", "id": res.data[0]['id']})
    except Exception as e:
        print(f"Add Receipt Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/add-expense', methods=['POST'])
def add_expense():
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        supabase.table('expenses').insert({
            "vendor_id": vendor['id'],
            "description": data.get('description'),
            "amount": float(data.get('amount'))
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/add-inventory', methods=['POST'])
def add_inventory():
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        supabase.table('inventory').insert({
            "vendor_id": vendor['id'],
            "item_name": data.get('item_name'),
            "stock_quantity": int(data.get('quantity'))
        }).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/update-inventory', methods=['POST'])
def update_inventory():
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        data = request.json
        supabase.table('inventory').update({"stock_quantity": int(data.get('quantity'))}).eq('id', data.get('id')).eq('vendor_id', vendor['id']).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/mark-paid/<int:receipt_id>', methods=['POST'])
def mark_paid(receipt_id):
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    try:
        supabase.table('receipts').update({'status': 'paid'}).eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/receipt/<int:receipt_id>')
def get_receipt(receipt_id):
    vendor = get_current_vendor()
    if not vendor: return jsonify({"error": "Unauthorized"}), 401
    res = supabase.table('receipts').select('*').eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
    if res.data:
        r = res.data[0]
        return jsonify({
            "id": r['id'], "name": r['customer_name'], "amount": float(r['amount']),
            "desc": r['item_desc'], "status": r['status'], "date": r['date'][:10],
            "business_name": vendor['business_name'], "phone": vendor.get('phone', ''),
            "ig_handle": vendor.get('ig_handle', ''), "bank_details": vendor.get('bank_details', '')
        })
    return jsonify({"error": "Not found"}), 404

@app.route('/download-pdf/<int:receipt_id>')
def download_pdf(receipt_id):
    vendor = get_current_vendor()
    if not vendor: return "Unauthorized", 401

    res = supabase.table('receipts').select('*').eq('id', receipt_id).eq('vendor_id', vendor['id']).execute()
    if not res.data: return "Receipt not found", 404

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
