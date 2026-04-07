from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime, timedelta
from database import DB_NAME, init_db, get_rental_days

app = Flask(__name__)
app.secret_key = "bookstore_secret_key"
init_db()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== ОБЩИЕ МАРШРУТЫ ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        conn = get_db()
        try:
            conn.execute("INSERT INTO users (username, password, email, role) VALUES (?, ?, ?, 'user')",
                        (username, password, email))
            conn.commit()
            flash('Регистрация успешна!', 'success')
            return redirect(url_for('login'))
        except:
            flash('Имя пользователя уже существует!', 'error')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", 
                           (username, password)).fetchone()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            # ВАЖНО: Сначала устанавливаем сессию, потом проверяем напоминания
            # И СОХРАНЯЕМ их в сессию, чтобы показать после редиректа
            reminders = check_and_send_reminders(user['id'])
            
            # Сохраняем напоминания в сессию
            session['pending_reminders'] = reminders
            
            flash(f'Добро пожаловать, {username}!', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_books'))
            return redirect(url_for('books'))
        flash('Неверные учетные данные!', 'error')
    return render_template('login.html')


def check_and_send_reminders(user_id, show_flash=True):
    """Автоматическая проверка аренд и отправка напоминаний"""
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    
    rentals = conn.execute('''SELECT rentals.*, books.title 
                              FROM rentals 
                              JOIN books ON rentals.book_id = books.id 
                              WHERE rentals.user_id = ? AND rentals.status = 'active' 
                              ORDER BY rentals.end_date''', (user_id,)).fetchall()
    
    reminders_sent = []
    
    for rental in rentals:
        end_date = rental['end_date']
        days_left = (datetime.strptime(end_date, '%Y-%m-%d') - datetime.now()).days
        
        should_remind = False
        message = ""
        
        if days_left < 0:
            should_remind = True
            message = f"⚠️ ВНИМАНИЕ! Срок аренды книги '{rental['title']}' истек {end_date}. Пожалуйста, верните книгу!"
        elif days_left == 0:
            should_remind = True
            message = f"🔔 Напоминание! Сегодня последний день аренды книги '{rental['title']}'. Пожалуйста, верните книгу!"
        elif days_left == 1:
            should_remind = True
            message = f"🔔 Напоминание! Срок аренды книги '{rental['title']}' истекает ЗАВТРА ({end_date})."
        elif days_left == 2:
            should_remind = True
            message = f"🔔 Напоминание! Срок аренды книги '{rental['title']}' истекает через 2 дня ({end_date})."
        elif days_left == 3:
            should_remind = True
            message = f"🔔 Напоминание! Срок аренды книги '{rental['title']}' истекает через 3 дня ({end_date})."
        
        if should_remind:
            existing = conn.execute('''SELECT id FROM reminders 
                                       WHERE rental_id = ? AND user_id = ? 
                                       AND sent_date LIKE ?''',
                                    (rental['id'], user_id, datetime.now().strftime('%Y-%m-%d') + '%')).fetchone()
            
            if not existing:
                conn.execute('''INSERT INTO reminders (rental_id, user_id, message, sent_date, status)
                               VALUES (?, ?, ?, ?, 'sent')''',
                            (rental['id'], user_id, message, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                reminders_sent.append(message)
    
    conn.commit()
    
    # ВОЗВРАЩАЕМ СПИСОК НАПОМИНАНИЙ, НО НЕ ПОКАЗЫВАЕМ ИХ СРАЗУ
    return reminders_sent


@app.route('/my-reminders')
def my_reminders():
    """Показывает все напоминания пользователя"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    reminders = conn.execute('''SELECT reminders.*, books.title 
                                FROM reminders 
                                JOIN rentals ON reminders.rental_id = rentals.id
                                JOIN books ON rentals.book_id = books.id
                                WHERE reminders.user_id = ? 
                                ORDER BY reminders.sent_date DESC''', 
                            (session['user_id'],)).fetchall()
    
    return render_template('my_reminders.html', reminders=reminders)

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('index'))

# ==================== ПОЛЬЗОВАТЕЛЬСКИЙ ИНТЕРФЕЙС ====================
@app.route('/books')
def books():
    # ========== ПОЛУЧАЕМ СВЕЖИЕ НАПОМИНАНИЯ ==========
    if 'user_id' in session and session.get('role') != 'admin':
        conn = get_db()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Получаем непрочитанные напоминания за сегодня
        new_reminders = conn.execute('''SELECT message FROM reminders 
                                        WHERE user_id = ? AND sent_date LIKE ? 
                                        ORDER BY id DESC''',
                                    (session['user_id'], today + '%')).fetchall()
        
        if new_reminders:
            reminders_list = [r['message'] for r in new_reminders]
            session['pending_reminders'] = reminders_list
        
        conn.close()
    
    # ========== ОСНОВНОЙ КОД СТРАНИЦЫ КАТАЛОГА КНИГ ==========
    conn = get_db()
    
    # Параметры фильтрации
    category = request.args.get('category', '')
    author = request.args.get('author', '')
    year = request.args.get('year', '')
    
    # Параметр сортировки
    sort_by = request.args.get('sort', 'title_asc')
    
    query = "SELECT * FROM books WHERE available = 1"
    params = []
    
    # Фильтры
    if category:
        query += " AND category = ?"
        params.append(category)
    if author:
        query += " AND author = ?"
        params.append(author)
    if year:
        query += " AND year = ?"
        params.append(year)
    
    # Сортировка
    if sort_by == 'title_asc':
        query += " ORDER BY title ASC"
    elif sort_by == 'title_desc':
        query += " ORDER BY title DESC"
    elif sort_by == 'author_asc':
        query += " ORDER BY author ASC"
    elif sort_by == 'author_desc':
        query += " ORDER BY author DESC"
    elif sort_by == 'category_asc':
        query += " ORDER BY category ASC"
    elif sort_by == 'category_desc':
        query += " ORDER BY category DESC"
    elif sort_by == 'year_asc':
        query += " ORDER BY year ASC"
    elif sort_by == 'year_desc':
        query += " ORDER BY year DESC"
    elif sort_by == 'price_asc':
        query += " ORDER BY price ASC"
    elif sort_by == 'price_desc':
        query += " ORDER BY price DESC"
    else:
        query += " ORDER BY title ASC"
    
    books = conn.execute(query, params).fetchall()
    
    # Получаем уникальные значения для фильтров
    categories = conn.execute("SELECT DISTINCT category FROM books WHERE available = 1").fetchall()
    authors = conn.execute("SELECT DISTINCT author FROM books WHERE available = 1").fetchall()
    years = conn.execute("SELECT DISTINCT year FROM books WHERE available = 1 ORDER BY year DESC").fetchall()
    
    conn.close()
    
    return render_template('books.html', 
                          books=books, 
                          categories=categories, 
                          authors=authors, 
                          years=years,
                          current_category=category, 
                          current_author=author, 
                          current_year=year,
                          current_sort=sort_by)

@app.route('/clear-reminders', methods=['POST'])
def clear_reminders():
    """Очищает напоминания из сессии после показа модального окна"""
    if 'pending_reminders' in session:
        session.pop('pending_reminders')
    return '', 200

@app.route('/book/<int:book_id>')
def book_detail(book_id):
    conn = get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    return render_template('book_detail.html', book=book)

@app.route('/rent/<int:book_id>', methods=['GET', 'POST'])
def rent_book(book_id):
    if 'user_id' not in session or session.get('role') != 'user':
        flash('Пожалуйста, войдите как пользователь', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    
    if request.method == 'POST':
        rent_type = request.form['rent_type']
        days = get_rental_days(rent_type)
        start_date = datetime.now().strftime('%Y-%m-%d')
        end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        
        conn.execute('''INSERT INTO rentals (book_id, user_id, rent_type, start_date, end_date, status)
                       VALUES (?, ?, ?, ?, ?, 'active')''',
                    (book_id, session['user_id'], rent_type, start_date, end_date))
        
        conn.execute("UPDATE books SET available = 0 WHERE id = ?", (book_id,))
        conn.commit()
        
        flash(f'Книга арендована на {days} дней! Срок до {end_date}', 'success')
        return redirect(url_for('my_rentals'))
    
    return render_template('rent_book.html', book=book)

@app.route('/my-rentals')
def my_rentals():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    
    sort_by = request.args.get('sort', 'end_date_asc')
    status_filter = request.args.get('status', '')
    
    query = '''SELECT rentals.*, books.title, books.author 
               FROM rentals 
               JOIN books ON rentals.book_id = books.id 
               WHERE rentals.user_id = ?'''
    params = [session['user_id']]
    
    if status_filter:
        query += " AND rentals.status = ?"
        params.append(status_filter)
    
    if sort_by == 'title_asc':
        query += " ORDER BY books.title ASC"
    elif sort_by == 'title_desc':
        query += " ORDER BY books.title DESC"
    elif sort_by == 'end_date_asc':
        query += " ORDER BY rentals.end_date ASC"
    elif sort_by == 'end_date_desc':
        query += " ORDER BY rentals.end_date DESC"
    elif sort_by == 'start_date_asc':
        query += " ORDER BY rentals.start_date ASC"
    elif sort_by == 'start_date_desc':
        query += " ORDER BY rentals.start_date DESC"
    else:
        query += " ORDER BY rentals.end_date ASC"
    
    rentals = conn.execute(query, params).fetchall()
    
    rentals_list = []
    for rental in rentals:
        rental_dict = dict(rental)
        rental_dict['is_overdue'] = rental['end_date'] < today
        rentals_list.append(rental_dict)
    
    return render_template('my_rentals.html', rentals=rentals_list, 
                          current_sort=sort_by, current_status=status_filter)

# ==================== АДМИНИСТРАТОРСКИЙ ИНТЕРФЕЙС ====================
def clear_user_reminders_session(user_id):
    """Очищает сессию пользователя от старых напоминаний"""
    # В Flask нет прямого доступа к сессиям других пользователей
    # Поэтому мы просто удаляем записи из БД и при следующем входе пользователя
    # напоминания пересоздадутся с новыми датами
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Удаляем старые неподтвержденные напоминания из БД
    conn.execute('''DELETE FROM reminders 
                    WHERE user_id = ? AND status = 'pending' 
                    AND sent_date < ?''', 
                (user_id, today))
    conn.commit()
    conn.close()



@app.route('/admin/books')
def admin_books():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'error')
        return redirect(url_for('login'))
    
    conn = get_db()
    
    # Параметры фильтрации
    category = request.args.get('category', '')
    author = request.args.get('author', '')
    year = request.args.get('year', '')
    available = request.args.get('available', '')
    
    # Параметр сортировки
    sort_by = request.args.get('sort', 'title_asc')
    
    query = "SELECT * FROM books WHERE 1=1"
    params = []
    
    # Фильтры
    if category:
        query += " AND category = ?"
        params.append(category)
    if author:
        query += " AND author = ?"
        params.append(author)
    if year:
        query += " AND year = ?"
        params.append(year)
    if available:
        query += " AND available = ?"
        params.append(available)
    
    # Сортировка
    if sort_by == 'title_asc':
        query += " ORDER BY title ASC"
    elif sort_by == 'title_desc':
        query += " ORDER BY title DESC"
    elif sort_by == 'author_asc':
        query += " ORDER BY author ASC"
    elif sort_by == 'author_desc':
        query += " ORDER BY author DESC"
    elif sort_by == 'category_asc':
        query += " ORDER BY category ASC"
    elif sort_by == 'category_desc':
        query += " ORDER BY category DESC"
    elif sort_by == 'year_asc':
        query += " ORDER BY year ASC"
    elif sort_by == 'year_desc':
        query += " ORDER BY year DESC"
    elif sort_by == 'price_asc':
        query += " ORDER BY price ASC"
    elif sort_by == 'price_desc':
        query += " ORDER BY price DESC"
    else:
        query += " ORDER BY title ASC"
    
    books = conn.execute(query, params).fetchall()
    
    # Получаем уникальные значения для фильтров
    categories = conn.execute("SELECT DISTINCT category FROM books").fetchall()
    authors = conn.execute("SELECT DISTINCT author FROM books").fetchall()
    years = conn.execute("SELECT DISTINCT year FROM books ORDER BY year DESC").fetchall()
    
    return render_template('admin_books.html', 
                          books=books,
                          categories=categories,
                          authors=authors,
                          years=years,
                          current_category=category,
                          current_author=author,
                          current_year=year,
                          current_available=available,
                          current_sort=sort_by)

@app.route('/admin/check-all-reminders')
def admin_check_all_reminders():
    """Администратор может принудительно проверить напоминания для всех пользователей"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    users = conn.execute("SELECT id, username FROM users WHERE role = 'user'").fetchall()
    
    total_reminders = 0
    for user in users:
        reminders = check_and_send_reminders(user['id'], show_flash=False)
        total_reminders += len(reminders)
    
    flash(f'✅ Проверка завершена! Отправлено {total_reminders} напоминаний для {len(users)} пользователей', 'success')
    return redirect(url_for('admin_rentals'))

@app.route('/admin/book/add', methods=['GET', 'POST'])
def admin_add_book():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO books 
                       (title, author, category, year, price, rent_price_2weeks, rent_price_month, rent_price_3months, available, description)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (request.form['title'], request.form['author'], request.form['category'],
                     request.form['year'], request.form['price'], request.form['rent_price_2weeks'],
                     request.form['rent_price_month'], request.form['rent_price_3months'],
                     request.form.get('available', 1), request.form['description']))
        conn.commit()
        flash('Книга добавлена!', 'success')
        return redirect(url_for('admin_books'))
    
    return render_template('admin_edit_book.html', book=None)

@app.route('/admin/book/edit/<int:book_id>', methods=['GET', 'POST'])
def admin_edit_book(book_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    
    # Проверяем, есть ли активная аренда у этой книги
    active_rental = conn.execute('''SELECT id FROM rentals 
                                    WHERE book_id = ? AND status = 'active' 
                                    LIMIT 1''', (book_id,)).fetchone()
    
    if request.method == 'POST':
        # Получаем значение доступности из формы
        is_available = 1 if 'available' in request.form else 0
        
        # Если книга в активной аренде, запрещаем менять доступность на "доступна"
        if active_rental and is_available == 1:
            flash('❌ Невозможно сделать книгу доступной! Книга находится в активной аренде.', 'error')
            return redirect(url_for('admin_edit_book', book_id=book_id))
        
        # Обновляем книгу
        conn.execute('''UPDATE books SET 
                       title=?, author=?, category=?, year=?, price=?, 
                       rent_price_2weeks=?, rent_price_month=?, rent_price_3months=?, 
                       available=?, description=?
                       WHERE id=?''',
                    (request.form['title'], request.form['author'], request.form['category'],
                     request.form['year'], request.form['price'], request.form['rent_price_2weeks'],
                     request.form['rent_price_month'], request.form['rent_price_3months'],
                     is_available, request.form['description'], book_id))
        conn.commit()
        flash('✅ Книга успешно обновлена!', 'success')
        return redirect(url_for('admin_books'))
    
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    
    # Передаем информацию об активной аренде в шаблон
    return render_template('admin_edit_book.html', 
                          book=book, 
                          has_active_rental=bool(active_rental))

@app.route('/admin/book/delete/<int:book_id>')
def admin_delete_book(book_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    flash('Книга удалена!', 'success')
    return redirect(url_for('admin_books'))

@app.route('/admin/rentals')
def admin_rentals():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    
    status_filter = request.args.get('status', '')
    sort_by = request.args.get('sort', 'end_date_asc')
    
    query = '''SELECT rentals.*, books.title, books.author, users.username, users.email 
               FROM rentals 
               JOIN books ON rentals.book_id = books.id 
               JOIN users ON rentals.user_id = users.id 
               WHERE 1=1'''
    params = []
    
    if status_filter:
        query += " AND rentals.status = ?"
        params.append(status_filter)
    
    if sort_by == 'title_asc':
        query += " ORDER BY books.title ASC"
    elif sort_by == 'title_desc':
        query += " ORDER BY books.title DESC"
    elif sort_by == 'username_asc':
        query += " ORDER BY users.username ASC"
    elif sort_by == 'username_desc':
        query += " ORDER BY users.username DESC"
    elif sort_by == 'end_date_asc':
        query += " ORDER BY rentals.end_date ASC"
    elif sort_by == 'end_date_desc':
        query += " ORDER BY rentals.end_date DESC"
    elif sort_by == 'start_date_asc':
        query += " ORDER BY rentals.start_date ASC"
    elif sort_by == 'start_date_desc':
        query += " ORDER BY rentals.start_date DESC"
    else:
        query += " ORDER BY rentals.end_date ASC"
    
    rentals = conn.execute(query, params).fetchall()
    
    rentals_list = []
    for rental in rentals:
        rental_dict = dict(rental)
        rental_dict['is_overdue'] = rental['end_date'] < today
        rentals_list.append(rental_dict)
    
    return render_template('admin_rentals.html', rentals=rentals_list, 
                          current_status=status_filter, current_sort=sort_by)

@app.route('/admin/rentals/edit/<int:rental_id>', methods=['GET', 'POST'])
def admin_edit_rental(rental_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    
    if request.method == 'POST':
        new_end_date = request.form['end_date']
        new_rent_type = request.form['rent_type']
        
        # Получаем user_id и book_id до обновления
        rental_before = conn.execute("SELECT user_id, book_id FROM rentals WHERE id = ?", (rental_id,)).fetchone()
        user_id = rental_before['user_id']
        book_id = rental_before['book_id']
        
        # ОБНОВЛЯЕМ ДАТУ ОКОНЧАНИЯ
        conn.execute("UPDATE rentals SET end_date = ?, rent_type = ? WHERE id = ?",
                    (new_end_date, new_rent_type, rental_id))
        
        # Если новая дата больше текущей, книга снова становится доступной? НЕТ
        # Если дата окончания изменилась, обновляем статус книги
        today = datetime.now().strftime('%Y-%m-%d')
        if new_end_date < today:
            # Если дата окончания в прошлом - книга просрочена, но все еще в аренде
            conn.execute("UPDATE books SET available = 0 WHERE id = ?", (book_id,))
        else:
            # Если дата окончания в будущем - книга все еще в аренде
            conn.execute("UPDATE books SET available = 0 WHERE id = ?", (book_id,))
        
        conn.commit()
        
        flash('✅ Дата окончания аренды обновлена!', 'success')
        
        # ========== ВАЖНО: ОЧИЩАЕМ СТАРЫЕ НАПОМИНАНИЯ ==========
        # Удаляем старые напоминания по этой аренде
        conn.execute("DELETE FROM reminders WHERE rental_id = ?", (rental_id,))
        conn.commit()
        
        # Создаем НОВЫЕ напоминания с актуальной датой
        new_reminders = check_and_send_reminders(user_id)
        
        if new_reminders:
            flash(f'📧 Отправлено {len(new_reminders)} новых напоминаний пользователю', 'info')
        else:
            flash('✅ Нет активных напоминаний для этого пользователя', 'info')
        
        return redirect(url_for('admin_rentals'))
    
    rental = conn.execute('''SELECT rentals.*, books.title, users.username, users.email 
                              FROM rentals 
                              JOIN books ON rentals.book_id = books.id 
                              JOIN users ON rentals.user_id = users.id 
                              WHERE rentals.id = ?''', (rental_id,)).fetchone()
    return render_template('admin_edit_rental.html', rental=rental)

@app.route('/admin/force-check-reminders/<int:user_id>')
def admin_force_check_reminders(user_id):
    """Принудительная проверка напоминаний для конкретного пользователя"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    # Очищаем старые напоминания из БД
    conn = get_db()
    conn.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
    conn.commit()
    
    # Создаем новые напоминания
    reminders = check_and_send_reminders(user_id)
    
    # Получаем имя пользователя
    user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    
    if reminders:
        flash(f'✅ Проверка завершена! Отправлено {len(reminders)} напоминаний пользователю {user["username"]}', 'success')
    else:
        flash(f'✅ У пользователя {user["username"]} нет активных напоминаний (срок аренды > 3 дней)', 'info')
    
    return redirect(url_for('admin_rentals'))

@app.route('/admin/rentals/return/<int:rental_id>')
def admin_return_book(rental_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    rental = conn.execute("SELECT book_id FROM rentals WHERE id = ?", (rental_id,)).fetchone()
    conn.execute("UPDATE rentals SET status = 'returned' WHERE id = ?", (rental_id,))
    conn.execute("UPDATE books SET available = 1 WHERE id = ?", (rental['book_id'],))
    conn.commit()
    flash('Книга возвращена!', 'success')
    return redirect(url_for('admin_rentals'))

# ==================== АДМИН: ПРОСМОТР ОТПРАВЛЕННЫХ НАПОМИНАНИЙ ====================

@app.route('/admin/all-reminders')
def admin_all_reminders():
    """Админ видит все отправленные напоминания"""
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db()
    reminders = conn.execute('''SELECT reminders.*, users.username, users.email, books.title 
                                FROM reminders 
                                JOIN users ON reminders.user_id = users.id 
                                JOIN rentals ON reminders.rental_id = rentals.id
                                JOIN books ON rentals.book_id = books.id
                                ORDER BY reminders.sent_date DESC''').fetchall()
    
    return render_template('admin_all_reminders.html', reminders=reminders)

if __name__ == '__main__':
    app.run(debug=True)