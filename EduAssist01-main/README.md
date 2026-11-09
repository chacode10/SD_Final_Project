# Classroom Command Hub

A solo teacher app (Flask + MySQL + Cloudinary). Every teacher runs their own copy with their own database.

## 1. Install (once)
- **Python 3.10+** from python.org. On Windows, tick **"Add Python to PATH"** during install.
- **VS Code** + the **Python** extension (by Microsoft).
- **MySQL**. Easiest on Windows: install **XAMPP**, open its control panel and press **Start** on MySQL.
  (On Ubuntu: `sudo apt install mysql-server`, then `sudo service mysql start`.)

## 2. Create the database
- XAMPP: open http://localhost/phpmyadmin -> **New** -> name `classroom_hub` -> Create.
- Or in any MySQL console: `CREATE DATABASE classroom_hub CHARACTER SET utf8mb4;`
The app creates all tables by itself.

## 3. Cloudinary
1. Sign up free at cloudinary.com.
2. Console -> **API Keys** -> copy the "API environment variable" (`cloudinary://...`).
3. Settings -> **Security** -> turn on **"Allow delivery of PDF and ZIP files"**, or PDFs won't open.

## 4. Set up the project in VS Code
1. VS Code -> **File -> Open Folder** -> choose the `classroom_hub` folder.
2. Open the terminal (**Ctrl + `**) and run:
   - Windows: `py -m venv venv` then `venv\Scripts\activate`
   - Ubuntu/Mac: `python3 -m venv venv` then `source venv/bin/activate`
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill it in (MySQL password, Cloudinary link).
5. Run `python app.py` (or press **F5**), then open **http://localhost:5000**.

Stop with Ctrl+C. Next time, just activate the venv and run `python app.py` again.

## Troubleshooting
- `Access denied for user` -> wrong `DB_USER` / `DB_PASSWORD` in `.env`.
- `Unknown database` -> you skipped step 2.
- `Can't connect to MySQL` -> MySQL isn't started (XAMPP Start button).
- Dashboard says "Local storage" -> `CLOUDINARY_URL` is missing or `.env` isn't in the project folder.
- No `DB_NAME` in `.env` -> the app quietly uses a local SQLite file instead of MySQL.

## Sharing with groupmates
Send the folder (or a GitHub repo). **Never send your `.env`** - it holds your passwords. Each person makes their own `.env` and database.
