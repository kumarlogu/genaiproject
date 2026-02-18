import os
import sqlite3
from flask import Flask, render_template, request, redirect
from dotenv import load_dotenv
from groq import Groq

# ---------------- LOAD ENV ---------------- #

load_dotenv()
app = Flask(__name__)

# ---------------- GROQ CONFIG ---------------- #

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in .env file")

client = Groq(api_key=GROQ_API_KEY)

# ---------------- DATABASE SETUP ---------------- #

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            description TEXT,
            tags TEXT,
            location TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- HOME ---------------- #

@app.route("/")
def index():
    return render_template("index.html")

# ---------------- REPORT ITEM ---------------- #

@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":

        item_name = request.form.get("item_name", "").strip()
        keywords = request.form.get("keywords", "").strip()
        location = request.form.get("location", "").strip()

        if not item_name or not keywords or not location:
            return "All fields are required."

        prompt = f"""
Generate:
1) A detailed searchable description
2) 5 short tags (comma separated)

Item Name: {item_name}
Keywords: {keywords}

Format exactly like this:

Description:
<text>

Tags:
tag1, tag2, tag3, tag4, tag5
"""

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )

            ai_text = response.choices[0].message.content.strip()

        except Exception as e:
            return f"Groq API Error: {str(e)}"

        # -------- CLEAN AI PARSING -------- #

        try:
            clean_text = ai_text.replace("Description:", "").replace("Tags:", "")
            lines = clean_text.strip().split("\n")

            description_lines = []
            tag_line = ""

            for line in lines:
                line = line.strip()
                if "," in line and len(line.split(",")) >= 3:
                    tag_line = line
                else:
                    description_lines.append(line)

            description = " ".join(description_lines).strip()
            tags = tag_line.strip() if tag_line else "AI generated"

        except Exception:
            description = ai_text.strip()
            tags = "AI generated"

        # -------- DATABASE INSERT -------- #

        conn = get_db_connection()

        existing = conn.execute(
            "SELECT * FROM items WHERE item_name = ? AND location = ? AND description = ?",
            (item_name, location, description)
        ).fetchone()

        if existing:
            conn.close()
            return "Item already exists in database."

        try:
            conn.execute(
                "INSERT INTO items (item_name, description, tags, location) VALUES (?, ?, ?, ?)",
                (item_name, description, tags, location),
            )
            conn.commit()
        except Exception as db_error:
            conn.close()
            return f"Database Error: {str(db_error)}"

        conn.close()
        return redirect("/search")

    return render_template("report.html")

# ---------------- SEARCH ---------------- #

@app.route("/search", methods=["GET", "POST"])
def search():
    results = []

    if request.method == "POST":
        query = request.form.get("query", "").strip()

        if query:
            conn = get_db_connection()
            results = conn.execute("""
                SELECT DISTINCT * FROM items
                WHERE item_name LIKE ?
                OR description LIKE ?
                OR tags LIKE ?
                OR location LIKE ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
            conn.close()

    return render_template("search.html", results=results)

# ---------------- CHATBOT ---------------- #

@app.route("/chat", methods=["GET", "POST"])
def chat():
    reply = ""

    if request.method == "POST":
        user_message = request.form.get("message", "").strip()

        if user_message:
            conn = get_db_connection()

            items = conn.execute("""
                SELECT * FROM items
                WHERE item_name LIKE ?
                OR description LIKE ?
                OR tags LIKE ?
                OR location LIKE ?
            """, (f"%{user_message}%", f"%{user_message}%",
                  f"%{user_message}%", f"%{user_message}%")).fetchall()

            conn.close()

            if items:
                reply = "🔍 I found matching items:<br><br>"
                for item in items:
                    reply += f"<b>{item['item_name']}</b> - {item['location']}<br>"
            else:
                try:
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[
                            {"role": "system", "content": "You are a helpful lost and found assistant."},
                            {"role": "user", "content": user_message}
                        ],
                        temperature=0.7
                    )
                    reply = response.choices[0].message.content

                except Exception as e:
                    reply = f"AI Error: {str(e)}"

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return reply

        return render_template("chatbot.html", reply=reply)

    return render_template("chatbot.html", reply=reply)


# ---------------- MAIN ---------------- #

if __name__ == "__main__":
    app.run(debug=True)
