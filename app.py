from flask import Flask, render_template, request, redirect, url_for, flash
from flask_mysqldb import MySQL
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from config import Config
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.from_object(Config)

mysql = MySQL(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---- User class ----
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

    def get_id(self):
        return str(self.id)

@login_manager.user_loader
def load_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT id, username, role FROM user WHERE id=%s", (user_id,))
    user = cur.fetchone()
    cur.close()
    if user:
        return User(user['id'], user['username'], user['role'])
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM user WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()
        if user and user['password'] == password:
            user_obj = User(user['id'], user['username'], user['role'])
            login_user(user_obj)
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'professor':
                return redirect(url_for('professor_dashboard'))
            elif user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ---- Admin routes ----
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    return render_template('admin_dashboard.html')

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        try:
            cur.execute("INSERT INTO user (username, password, role) VALUES (%s, %s, %s)",
                        (username, password, role))
            mysql.connection.commit()
            flash('Utilisateur créé avec succès.', 'success')
        except Exception:
            flash('Erreur lors de la création de l\'utilisateur.', 'error')
    cur.execute("SELECT id, username, role FROM user")
    users = cur.fetchall()
    cur.close()
    return render_template('manage_users.html', users=users)

# ---- Professor routes ----
@app.route('/professor')
@login_required
def professor_dashboard():
    if current_user.role != 'professor':
        return redirect(url_for('index'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM course WHERE professor_id = %s", (current_user.id,))
    courses = cur.fetchall()
    cur.close()
    return render_template('professor_dashboard.html', courses=courses)

@app.route('/professor/create_course', methods=['GET', 'POST'])
@login_required
def create_course():
    if current_user.role != 'professor':
        return redirect(url_for('index'))
    if request.method == 'POST':
        course_name = request.form['course_name']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO course (name, professor_id) VALUES (%s, %s)", (course_name, current_user.id))
        mysql.connection.commit()
        cur.close()
        flash('Cours créé avec succès.', 'success')
        return redirect(url_for('professor_dashboard'))
    return render_template('create_course.html')

@app.route('/professor/course/<int:course_id>', methods=['GET', 'POST'])
@login_required
def course_detail(course_id):
    if current_user.role != 'professor':
        return redirect(url_for('index'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM course WHERE id=%s AND professor_id=%s", (course_id, current_user.id))
    course = cur.fetchone()
    if not course:
        cur.close()
        return redirect(url_for('professor_dashboard'))

    # Liste des étudiants déjà inscrits
    cur.execute("""
        SELECT u.id, u.username, g.grade, e.id as enrollment_id FROM enrollment e
        JOIN user u ON u.id = e.student_id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        WHERE e.course_id=%s
    """, (course_id,))
    students = cur.fetchall()

    # Liste des étudiants non inscrits pour le dropdown
    cur.execute("""
        SELECT id, username FROM user 
        WHERE role='student' AND id NOT IN (
            SELECT student_id FROM enrollment WHERE course_id=%s
        )
    """, (course_id,))
    all_students = cur.fetchall()

    # Traitement formulaire d'ajout OU modification de note
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        grade = request.form.get('grade')
        if student_id:
            # Vérifie si l'étudiant est déjà inscrit
            cur.execute("SELECT id FROM enrollment WHERE student_id=%s AND course_id=%s", (student_id, course_id))
            enrollment = cur.fetchone()
            if not enrollment:
                cur.execute("INSERT INTO enrollment (student_id, course_id) VALUES (%s, %s)", (student_id, course_id))
                mysql.connection.commit()
                cur.execute("SELECT id FROM enrollment WHERE student_id=%s AND course_id=%s", (student_id, course_id))
                enrollment = cur.fetchone()
                flash('Étudiant inscrit avec succès.', 'success')
            if grade:  # Ajout ou modification de la note
                # Vérifie si une note existe déjà
                cur.execute("SELECT grade FROM grade WHERE enrollment_id=%s", (enrollment['id'],))
                grade_row = cur.fetchone()
                if grade_row:
                    cur.execute("UPDATE grade SET grade=%s WHERE enrollment_id=%s", (grade, enrollment['id']))
                else:
                    cur.execute("INSERT INTO grade (enrollment_id, grade) VALUES (%s, %s)", (enrollment['id'], grade))
                mysql.connection.commit()
                flash('Note enregistrée.', 'success')
            return redirect(url_for('course_detail', course_id=course_id))
        # Mise à jour d'une note par formulaire rapide (modification sur une ligne)
        elif request.form.get('update_grade_student_id'):
            sid = request.form['update_grade_student_id']
            enrollment_id = request.form['update_grade_enrollment_id']
            new_grade = request.form['update_grade_value']
            cur.execute("SELECT grade FROM grade WHERE enrollment_id=%s", (enrollment_id,))
            grade_row = cur.fetchone()
            if grade_row:
                cur.execute("UPDATE grade SET grade=%s WHERE enrollment_id=%s", (new_grade, enrollment_id))
            else:
                cur.execute("INSERT INTO grade (enrollment_id, grade) VALUES (%s, %s)", (enrollment_id, new_grade))
            mysql.connection.commit()
            flash('Note modifiée.', 'success')
            return redirect(url_for('course_detail', course_id=course_id))

    cur.close()
    return render_template('course_detail.html', course=course, students=students, all_students=all_students)

# ---- Student routes ----
@app.route('/student')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        return redirect(url_for('index'))
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.name as course_name, u.username as professor_username, g.grade
        FROM enrollment e
        JOIN course c ON c.id = e.course_id
        JOIN user u ON u.id = c.professor_id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        WHERE e.student_id=%s
    """, (current_user.id,))
    enrollments = cur.fetchall()
    cur.close()
    return render_template('student_dashboard.html', enrollments=enrollments)

# ---- Profil utilisateur (tous rôles) ----
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    cur = mysql.connection.cursor()
    if request.method == 'POST':
        introduction = request.form.get('introduction', '')
        photo = request.files.get('photo', None)
        photo_filename = current_user.username + '.jpg'
        if photo and allowed_file(photo.filename):
            filename = secure_filename(current_user.username + '.' + photo.filename.rsplit('.', 1)[1].lower())
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            photo_filename = filename
            cur.execute("UPDATE user SET introduction=%s, photo=%s WHERE id=%s",
                        (introduction, photo_filename, current_user.id))
        else:
            cur.execute("UPDATE user SET introduction=%s WHERE id=%s",
                        (introduction, current_user.id))
        mysql.connection.commit()
        flash('Profil mis à jour.', 'success')
        cur.close()
        return redirect(url_for('profile'))
    cur.execute("SELECT username, email, introduction, photo FROM user WHERE id=%s", (current_user.id,))
    user = cur.fetchone()
    cur.close()
    return render_template('profile.html', user=user)

@app.route('/admin/courses')
@login_required
def admin_courses():
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT c.id AS course_id, c.name AS course_name, 
               p.username AS professor_name, 
               s.username AS student_name, 
               g.grade
        FROM course c
        JOIN user p ON c.professor_id = p.id
        LEFT JOIN enrollment e ON e.course_id = c.id
        LEFT JOIN user s ON e.student_id = s.id
        LEFT JOIN grade g ON g.enrollment_id = e.id
        ORDER BY c.name, s.username
    """)
    rows = cur.fetchall()
    cur.close()
    courses = {}
    for row in rows:
        cid = row['course_id']
        if cid not in courses:
            courses[cid] = {
                'course_name': row['course_name'],
                'professor_name': row['professor_name'],
                'students': []
            }
        if row['student_name']:
            courses[cid]['students'].append({
                'student_name': row['student_name'],
                'grade': row['grade']
            })
    return render_template('admin_courses.html', courses=courses)

app.config['UPLOAD_FOLDER'] = Config.UPLOAD_FOLDER
ALLOWED_EXTENSIONS = Config.ALLOWED_EXTENSIONS

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == '__main__':
    app.run(debug=True)