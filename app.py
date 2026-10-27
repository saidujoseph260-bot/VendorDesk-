from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import os
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
DB_FILE = 'vendordesk.db'
PDF_DIR = 'static'

if not os.path.exists(PDF_DIR):
    os.makedirs(PDF_DIR)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            amount REAL,
            item_desc TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    # Get the time filter from the web address (default is 'all')
    time_filter = request.args.get('filter', 'all')
    
    where_clause = ""
    if time_filter == 'today':
        where_clause = "WHERE date >= date('now')"
    elif time_filter == 'week':
        where_clause = "WHERE date >= date('now', '-7 days')"
    elif time_filter == 'month':
        where_clause = "WHERE date >= date('now', '-1 month')"
    elif time_filter == 'year':
        where_clause = "WHERE date >= date('now', '-1 year')"

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute(f"SELECT SUM(amount) FROM receipts {where_clause}")
    total_revenue = c.fetchone()[0] or 0
    
    c.execute(f"SELECT COUNT(id) FROM receipts {where_clause}")
    total_invoices = c.fetchone()[0] or 0
    
    c.execute(f"SELECT id, customer_name, amount, item_desc, date FROM receipts {where_clause} ORDER BY id DESC LIMIT 50")
    recent_receipts = c.fetchall()
    
    conn.close()
    
    return render_template('index.html', 
                           revenue=total_revenue, 
                           invoices=total_invoices, 
                           receipts=recent_receipts,
                           current_filter=time_filter)

@app.route('/add', methods=['POST'])
def add_receipt():
    data = request.get_json()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO receipts (customer_name, amount, item_desc) VALUES (?, ?, ?)", 
              (data['name'], data['amount'], data['desc']))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/receipt/<int:receipt_id>')
def get_receipt(receipt_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, customer_name, amount, item_desc, date FROM receipts WHERE id = ?", (receipt_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({"id": row[0], "name": row[1], "amount": row[2], "desc": row[3], "date": row[4]})
    return jsonify({"error": "Not found"}), 404

@app.route('/download-pdf/<int:receipt_id>')
def download_pdf(receipt_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT customer_name, amount, item_desc, date FROM receipts WHERE id = ?", (receipt_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return "Receipt not found", 404
        
    pdf_filename = f"receipt_{receipt_id}.pdf"
    pdf_path = os.path.join(PDF_DIR, pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    story.append(Paragraph("<b>VENDOR DESK INVOICE</b>", styles['Title']))
    story.append(Spacer(1, 20))
    story.append(Paragraph(f"<b>Date:</b> {row[3]}", styles['Normal']))
    story.append(Paragraph(f"<b>Customer Name:</b> {row[0]}", styles['Normal']))
    story.append(Paragraph(f"<b>Item Description:</b> {row[2]}", styles['Normal']))
    story.append(Paragraph(f"<b>Total Paid:</b> NGN {row[1]:,.2f}", styles['Heading2']))
    story.append(Spacer(1, 30))
    story.append(Paragraph("<i>Thank you for your patronage! Powered by VendorDesk.</i>", styles['Italic']))
    
    doc.build(story)
    
    # Changed to as_attachment=False so Chrome opens it instead of downloading it to Acode
    return send_file(pdf_path, as_attachment=False)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
