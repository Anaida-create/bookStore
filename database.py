import sqlite3
from datetime import datetime, timedelta

DB_NAME = "bookstore.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'user'
        )''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            year INTEGER NOT NULL,
            price REAL NOT NULL,
            rent_price_2weeks REAL NOT NULL,
            rent_price_month REAL NOT NULL,
            rent_price_3months REAL NOT NULL,
            available INTEGER DEFAULT 1,
            description TEXT
        )''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS rentals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER,
            user_id INTEGER,
            rent_type TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            FOREIGN KEY(book_id) REFERENCES books(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        
        cur.execute('''CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rental_id INTEGER,
            user_id INTEGER,
            message TEXT,
            sent_date TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(rental_id) REFERENCES rentals(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        
        cur.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
                       ('admin', 'admin123', 'admin@bookstore.com', 'admin'))
            cur.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, ?)",
                       ('user', 'user123', 'user@example.com', 'user'))
            
            books_data = [
                ('Мастер и Маргарита', 'Михаил Булгаков', 'Классика', 1967, 599, 99, 149, 199, 1, 'Роман о любви и дьяволе'),
                ('Преступление и наказание', 'Фёдор Достоевский', 'Классика', 1866, 499, 89, 139, 179, 1, 'Психологический роман'),
                ('Гарри Поттер и философский камень', 'Джоан Роулинг', 'Фэнтези', 1997, 699, 129, 199, 249, 1, 'Первая книга о Гарри Поттере'),
                ('Властелин колец', 'Джон Толкин', 'Фэнтези', 1954, 899, 159, 249, 299, 1, 'Эпическая фэнтези-сага'),
                ('451 градус по Фаренгейту', 'Рэй Брэдбери', 'Фантастика', 1953, 449, 79, 119, 159, 1, 'Роман-антиутопия'),
                ('1984', 'Джордж Оруэлл', 'Фантастика', 1949, 499, 89, 139, 179, 1, 'Знаменитая антиутопия'),
                ('Алхимик', 'Пауло Коэльо', 'Притча', 1988, 399, 69, 99, 139, 1, 'Книга о поиске своей судьбы'),
                ('Три товарища', 'Эрих Ремарк', 'Роман', 1936, 549, 99, 149, 189, 1, 'О дружбе и любви'),
            ]
            
            for book in books_data:
                cur.execute('''INSERT INTO books 
                    (title, author, category, year, price, rent_price_2weeks, rent_price_month, rent_price_3months, available, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', book)
        
        conn.commit()

def get_rental_days(rent_type):
    if rent_type == '2weeks':
        return 14
    elif rent_type == 'month':
        return 30
    elif rent_type == '3months':
        return 90
    return 14
