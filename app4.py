import streamlit as st

# ✅ Streamlit page config
st.set_page_config(page_title="Smart Resume Analyzer", page_icon='./Logo/SRA_Logo.ico')

# Imports
import nltk
import spacy
import pandas as pd
import base64
import random
import datetime
import os
import pymysql
import io
import re
from pyresparser import ResumeParser, utils as pr_utils
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter

from streamlit_tags import st_tags
from PIL import Image
import plotly.express as px

# ✅ Download NLTK stopwords
nltk.download('stopwords')

# ---------------------------
# Safe spaCy loader function
# ---------------------------
def safe_load_model(model="en_core_web_sm"):
    try:
        return spacy.load(model)
    except OSError:
        from spacy.cli import download
        download(model)
        return spacy.load(model)

try:
    nlp = safe_load_model()
except Exception as e:
    st.warning(f"Warning: unable to load spaCy model: {e}")
    nlp = None

# ---------------------------
# Patch ResumeParser __init__
# ---------------------------
if not hasattr(ResumeParser, "_patched"):
    _old_init = ResumeParser.__init__

    def patched_init(self, resume, skills_file=None, custom_nlp=None, custom_regex=None):
        """
        Wrapped constructor:
         - Ensures spaCy model is available.
         - Stores custom_regex separately (not passed to original init).
        """
        nlp_model = custom_nlp or safe_load_model()
        # Call original constructor (only allowed args)
        _old_init(self, resume, skills_file, nlp_model)
        # Store regex safely
        if not custom_regex or not isinstance(custom_regex, (str, bytes)):
            custom_regex = r'(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{4,6}'
        self._custom_regex = custom_regex

    ResumeParser.__init__ = patched_init
    ResumeParser._patched = True

# ---------------------------
# Monkey patch extract_mobile_number
# ---------------------------
def safe_extract_mobile_number(text, custom_regex=None):
    if not text or not isinstance(text, str):
        return None
    if not custom_regex or not isinstance(custom_regex, (str, bytes)):
        custom_regex = r'(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,5}[-.\s]?\d{4,6}'
    try:
        matches = re.findall(re.compile(custom_regex), text)
        if not matches:
            return None
        first = matches[0]
        if isinstance(first, tuple):
            return ''.join(first).strip()
        return first
    except Exception:
        fallback = r'(\+?\d{1,3}[-.\s]?)?\d{6,15}'
        try:
            matches = re.findall(re.compile(fallback), text)
            if not matches:
                return None
            first = matches[0]
            if isinstance(first, tuple):
                return ''.join(first).strip()
            return first
        except Exception:
            return None

pr_utils.extract_mobile_number = safe_extract_mobile_number

# ---------------------------
# Import course data
# ---------------------------
from Courses import ds_course, web_course, android_course, ios_course, uiux_course, resume_videos, interview_videos

# ---------------------------
# DB connection
# ---------------------------
def create_db_connection():
    try:
        return pymysql.connect(host='localhost', user='root', password='root', autocommit=True)
    except pymysql.Error as e:
        st.error(f"Database connection error: {e}")
        return None

connection = create_db_connection()
cursor = connection.cursor() if connection else None

# ---------------------------
# Utility Functions
# ---------------------------
def get_table_download_link(df, filename, text):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'

def pdf_reader(file_path):
    resource_manager = PDFResourceManager()
    fake_file_handle = io.StringIO()
    converter = TextConverter(resource_manager, fake_file_handle, laparams=LAParams())
    page_interpreter = PDFPageInterpreter(resource_manager, converter)
    with open(file_path, 'rb') as fh:
        for page in PDFPage.get_pages(fh, caching=True, check_extractable=True):
            page_interpreter.process_page(page)
        text = fake_file_handle.getvalue()
    converter.close()
    fake_file_handle.close()
    return text

def show_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# ---------------------------
# Resume Analyzer
# ---------------------------
def analyze_resume(uploaded_file):
    save_path = './Uploaded_Resumes/' + uploaded_file.name
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    show_pdf(save_path)
    try:
        parsed = ResumeParser(save_path).get_extracted_data()
        if not isinstance(parsed, dict):
            parsed = {"raw_text": pdf_reader(save_path), "skills": []}
        return parsed, save_path
    except Exception as e:
        st.warning(f"Resume parsing failed: {e}. Using fallback text extraction.")
        text = pdf_reader(save_path)
        return {
            "name": None, "email": None, "mobile_number": None,
            "education": None, "experience": [], "skills": [],
            "raw_text": text, "no_of_pages": None
        }, save_path


# ---------------------------
# DB Functions
# ---------------------------
def create_user_table():
    if not connection:
        return
    try:
        cursor.execute("CREATE DATABASE IF NOT EXISTS sra;")
        cursor.execute("USE sra;")

        # Drop and recreate table with proper schema
        cursor.execute("DROP TABLE IF EXISTS resume_data;")
        cursor.execute("""
            CREATE TABLE resume_data (
                ID INT NOT NULL AUTO_INCREMENT,
                name VARCHAR(100),
                email VARCHAR(100),
                resume_score VARCHAR(8),
                timestamp VARCHAR(50),
                no_of_pages VARCHAR(5),
                predicted_field VARCHAR(50),
                user_level VARCHAR(30),
                skills TEXT,
                Recommended_skills TEXT,
                Recommended_courses TEXT,
                PRIMARY KEY (ID)
            );
        """)
        connection.commit()
    except pymysql.Error as e:
        st.error(f"Error creating table: {e}")


def insert_data(name, email, resume_score, timestamp, no_of_pages,
                predicted_field, candidate_level, skills,
                recommended_skills, rec_course):
    if not connection:
        return
    try:
        insert_sql = """INSERT INTO resume_data 
        (name, email, resume_score, timestamp, no_of_pages,
         predicted_field, user_level, skills, Recommended_skills, Recommended_courses)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        values = (
            name, email, resume_score, timestamp, no_of_pages,
            predicted_field, candidate_level,
            str(skills), str(recommended_skills), str(rec_course)
        )
        cursor.execute("USE sra;")
        cursor.execute(insert_sql, values)
        connection.commit()
        st.success("Your resume data has been stored successfully!")
    except pymysql.Error as e:
        st.error(f"Error inserting data: {e}")
        connection.rollback()


# ---------------------------
# Skills & Scoring
# ---------------------------
def display_video_tips():
    st.header("**Bonus Video for Resume Writing Tips💡**")
    if resume_videos:
        st.video(random.choice(resume_videos))
    st.header("**Bonus Video for Interview👨‍💼 Tips💡**")
    if interview_videos:
        st.video(random.choice(interview_videos))

def calculate_resume_score(resume_data, predicted_field, recommended_skills):
    score = 0
    if resume_data.get('name'): score += 10
    if resume_data.get('email'): score += 10
    if resume_data.get('mobile_number'): score += 10
    if resume_data.get('education'): score += 15
    if resume_data.get('experience'): score += 20
    if resume_data.get('skills'): score += 15
    extracted = [skill.lower() for skill in resume_data.get('skills', [])]
    score += sum(5 for skill in recommended_skills if skill.lower() in extracted)
    no_pages = resume_data.get('no_of_pages', 1) or 1
    try:
        no_pages = int(no_pages)
    except Exception:
        no_pages = 1
    if no_pages <= 2:
        score += 10
    elif no_pages > 3:
        score -= 5
    return min(100, score)

def analyze_skills(resume_data):
    skills = resume_data.get("skills", []) or []
    recommended_skills, predicted_field, rec_course = [], "Unknown", []
    lower_skills = [s.lower() for s in skills]
    if "python" in lower_skills:
        recommended_skills = ["Machine Learning", "Data Science", "Artificial Intelligence"]
        predicted_field = "Data Science"
        rec_course = ds_course
    elif "java" in lower_skills:
        recommended_skills = ["Java Development", "Spring Framework", "Web Development"]
        predicted_field = "Software Development"
        rec_course = android_course
    elif "web development" in lower_skills:
        recommended_skills = ["HTML", "CSS", "JavaScript", "React", "Node.js"]
        predicted_field = "Web Development"
        rec_course = web_course
    return recommended_skills, predicted_field, rec_course

# ---------------------------
# UI Handlers
# ---------------------------
def handle_normal_user():
    pdf_file = st.file_uploader("Choose your Resume", type=["pdf"])
    if pdf_file:
        resume_data, save_path = analyze_resume(pdf_file)
        if resume_data:
            st.success(f"Hello {resume_data.get('name', 'User')}")
            st.text(f"Name: {resume_data.get('name', 'N/A')}")
            st.text(f"Email: {resume_data.get('email', 'N/A')}")
            st.text(f"Contact: {resume_data.get('mobile_number', 'N/A')}")
            st.text(f"Resume pages: {str(resume_data.get('no_of_pages', 'N/A'))}")
            recommended_skills, predicted_field, rec_course = analyze_skills(resume_data)
            resume_score = calculate_resume_score(resume_data, predicted_field, recommended_skills)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            experience = resume_data.get('experience', []) or []
            candidate_level = "Beginner" if not experience else "Intermediate" if len(experience) <= 3 else "Expert"
            st.subheader("**Skills Recommendation💡**")
            st_tags(label='### Skills that you have', text='Extracted skills', value=resume_data.get('skills', []), key='1')
            st_tags(label='### Recommended skills for you.', value=recommended_skills, key='2')
            course_recommender(rec_course)
            st.success(f"** Your Resume Writing Score: {resume_score:.2f} **")
            st.progress(resume_score / 100.0)
            insert_data(resume_data.get('name', 'N/A'), resume_data.get('email', 'N/A'), resume_score, timestamp,
                        resume_data.get('no_of_pages', '0'), predicted_field, candidate_level,
                        resume_data.get('skills', []), recommended_skills, rec_course)
            display_video_tips()

def course_recommender(course_list):
    st.subheader("**Courses & Certificates🎓 Recommendations**")
    rec_course = []
    no_of_reco = st.slider('Choose Number of Course Recommendations:', 1, 10, 4)
    random.shuffle(course_list)
    for c, (c_name, c_link) in enumerate(course_list):
        if c == no_of_reco: break
        st.markdown(f"({c+1}) [{c_name}]({c_link})")
        rec_course.append(c_name)
    return rec_course

def handle_admin():
    st.success('Welcome to Admin Side')
    ad_user = st.text_input("Username")
    ad_password = st.text_input("Password", type='password')
    if st.button('Login'):
        if ad_user == "Amigoes" and ad_password == "Amigoes":
            st.success("Welcome Admin")
            if not connection:
                st.error("Database connection is not available.")
                return
            try:
                cursor.execute("USE sra;")
                cursor.execute("SELECT * FROM resume_data")
                data = cursor.fetchall()
                if data:
                    df = pd.DataFrame(data, columns=['ID', 'Name', 'Email', 'Resume Score', 'Timestamp',
                                                     'Total Page', 'Predicted Field', 'User Level',
                                                     'Skills', 'Recommended Skills', 'Recommended Course'])
                    st.dataframe(df)
                    st.markdown(get_table_download_link(df, 'User_Data.csv', 'Download Report'), unsafe_allow_html=True)
                    field_counts = df['Predicted Field'].value_counts()
                    st.plotly_chart(px.pie(names=field_counts.index, values=field_counts.values, title='Predicted Field'))
                    level_counts = df['User Level'].value_counts()
                    st.plotly_chart(px.pie(names=level_counts.index, values=level_counts.values, title="User Experience Level"))
                else:
                    st.warning("No data found in the database")
            except pymysql.Error as e:
                st.error(f"Error fetching data: {e}")
        else:
            st.error("Wrong ID & Password Provided")

def run():
    st.title("Smart Resume Analyser")
    if connection: create_user_table()
    choice = st.sidebar.selectbox("Choose among the given options:", ["Normal User", "Admin"])
    try:
        img = Image.open('./Logo/SRA_Logo.jpg').resize((250, 250))
        st.image(img)
    except Exception: pass
    if choice == 'Normal User': handle_normal_user()
    else: handle_admin()

if __name__ == "__main__":
    run()
