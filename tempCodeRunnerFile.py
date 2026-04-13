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
from pyresparser import ResumeParser
from pdfminer.layout import LAParams
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter

from streamlit_tags import st_tags
from PIL import Image
import plotly.express as px

# ✅ Download NLTK stopwords
nltk.download('stopwords')

# ✅ Load spaCy model safely
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    from spacy.cli import download
    download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# ✅ Patch ResumeParser to fix config.cfg / spaCy load issues
def safe_load_model(model="en_core_web_sm"):
    """Ensure spaCy model is available and loadable."""
    try:
        return spacy.load(model)
    except OSError:
        from spacy.cli import download
        download(model)
        return spacy.load(model)

_old_init = ResumeParser.__init__

def patched_init(self, resume, skills_file=None, custom_nlp=None):
    # Call original init, but enforce our safe spaCy loader
    _old_init(self, resume, skills_file, custom_nlp or safe_load_model())

ResumeParser.__init__ = patched_init

# ✅ Import course data
from Courses import ds_course, web_course, android_course, ios_course, uiux_course, resume_videos, interview_videos

# ✅ DB connection
def create_db_connection():
    try:
        return pymysql.connect(host='localhost', user='root', password='root', database='sra')
    except pymysql.Error as e:
        st.error(f"Database connection error: {e}")
        return None

connection = create_db_connection()
if connection:
    cursor = connection.cursor()

# Utility Functions
def get_table_download_link(df, filename, text):
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    return f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'

def pdf_reader(file):
    resource_manager = PDFResourceManager()
    fake_file_handle = io.StringIO()
    converter = TextConverter(resource_manager, fake_file_handle, laparams=LAParams())
    page_interpreter = PDFPageInterpreter(resource_manager, converter)
    with open(file, 'rb') as fh:
        for page in PDFPage.get_pages(fh, caching=True, check_extractable=True):
            page_interpreter.process_page(page)
        text = fake_file_handle.getvalue()
    converter.close()
    fake_file_handle.close()
    return text

def show_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

def analyze_resume(file):
    save_path = './Uploaded_Resumes/' + file.name
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(file.getbuffer())
    show_pdf(save_path)
    return ResumeParser(save_path).get_extracted_data(), save_path

def course_recommender(course_list):
    st.subheader("**Courses & Certificates🎓 Recommendations**")
    rec_course = []
    no_of_reco = st.slider('Choose Number of Course Recommendations:', 1, 10, 4)
    random.shuffle(course_list)
    for c, (c_name, c_link) in enumerate(course_list):
        if c == no_of_reco:
            break
        st.markdown(f"({c+1}) [{c_name}]({c_link})")
        rec_course.append(c_name)
    return rec_course

def create_user_table():
    try:
        cursor.execute("CREATE DATABASE IF NOT EXISTS sra;")
        cursor.execute("USE sra;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_data (
                ID INT NOT NULL AUTO_INCREMENT,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(50) NOT NULL,
                resume_score VARCHAR(8) NOT NULL,
                timestamp VARCHAR(50) NOT NULL,
                no_of_pages VARCHAR(5) NOT NULL,
                reco_field VARCHAR(25) NOT NULL,
                user_level VARCHAR(30) NOT NULL,
                skills VARCHAR(300) NOT NULL,
                Recommended_skills VARCHAR(300) NOT NULL,
                Recommended_courses VARCHAR(600) NOT NULL,
                PRIMARY KEY (ID)
            );
        """)
        connection.commit()
    except pymysql.Error as e:
        st.error(f"Error creating table: {e}")

def insert_data(name, email, resume_score, timestamp, no_of_pages, reco_field, candidate_level, skills, recommended_skills, rec_course):
    try:
        insert_sql = """INSERT INTO resume_data 
        (name, email, resume_score, timestamp, no_of_pages, reco_field, user_level, skills, Recommended_skills, Recommended_courses)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        values = (name, email, resume_score, timestamp, no_of_pages, reco_field, candidate_level,
                  str(skills), str(recommended_skills), str(rec_course))
        cursor.execute(insert_sql, values)
        connection.commit()
        st.success("Your resume data has been stored successfully!")
    except pymysql.Error as e:
        st.error(f"Error inserting data: {e}")
        connection.rollback()

def display_video_tips():
    st.header("**Bonus Video for Resume Writing Tips💡**")
    if resume_videos:
        st.video(random.choice(resume_videos))
    else:
        st.warning("No resume videos available")
    st.header("**Bonus Video for Interview👨‍💼 Tips💡**")
    if interview_videos:
        st.video(random.choice(interview_videos))
    else:
        st.warning("No interview videos available")

def calculate_resume_score(resume_data, reco_field, recommended_skills):
    score = 0
    if resume_data.get('name'): score += 10
    if resume_data.get('email'): score += 10
    if resume_data.get('mobile_number'): score += 10
    if resume_data.get('education'): score += 15
    if resume_data.get('experience'): score += 20
    if resume_data.get('skills'): score += 15

    extracted = [skill.lower() for skill in resume_data.get('skills', [])]
    matched = sum(5 for skill in recommended_skills if skill.lower() in extracted)
    score += matched

    if resume_data.get('no_of_pages', 1) <= 2:
        score += 10
    elif resume_data.get('no_of_pages', 1) > 3:
        score -= 5
    return min(100, score)

def analyze_skills(resume_data):
    skills = resume_data.get("skills", [])
    recommended_skills, reco_field, rec_course = [], "Unknown", []

    lower_skills = [s.lower() for s in skills]
    if "python" in lower_skills:
        recommended_skills = ["Machine Learning", "Data Science", "Artificial Intelligence"]
        reco_field = "Data Science"
        rec_course = ds_course
    elif "java" in lower_skills:
        recommended_skills = ["Java Development", "Spring Framework", "Web Development"]
        reco_field = "Software Development"
        rec_course = android_course
    elif "web development" in lower_skills:
        recommended_skills = ["HTML", "CSS", "JavaScript", "React", "Node.js"]
        reco_field = "Web Development"
        rec_course = web_course

    return recommended_skills, reco_field, rec_course

def handle_normal_user():
    pdf_file = st.file_uploader("Choose your Resume", type=["pdf"])
    if pdf_file:
        resume_data, save_path = analyze_resume(pdf_file)
        if resume_data:
            st.success(f"Hello {resume_data.get('name')}")
            st.subheader("**Your Basic info**")
            try:
                st.text(f"Name: {resume_data['name']}")
                st.text(f"Email: {resume_data['email']}")
                st.text(f"Contact: {resume_data['mobile_number']}")
                st.text(f"Resume pages: {str(resume_data['no_of_pages'])}")
            except KeyError:
                st.warning("Some basic details are missing.")

            recommended_skills, reco_field, rec_course = analyze_skills(resume_data)
            resume_score = calculate_resume_score(resume_data, reco_field, recommended_skills)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            experience = resume_data.get('experience', [])
            candidate_level = "Beginner" if not experience else "Intermediate" if len(experience) <= 3 else "Expert"

            st.subheader("**Skills Recommendation💡**")
            st_tags(label='### Skills that you have', text='Extracted skills', value=resume_data['skills'], key='1')
            st.success(f"** Recommended skills for {reco_field}: **")
            st_tags(label='### Recommended skills for you.', value=recommended_skills, key='2')

            course_recommender(rec_course)
            st.subheader("**Resume Tips & Ideas💡**")
            st.success(f"** Your Resume Writing Score: {resume_score:.2f} **")
            st.warning("** Note: This score is based on the content of your resume. **")
            st.progress(resume_score / 100.0)

            insert_data(resume_data['name'], resume_data['email'], resume_score, timestamp,
                        resume_data['no_of_pages'], reco_field, candidate_level,
                        resume_data['skills'], recommended_skills, rec_course)

            display_video_tips()
        else:
            st.error('Failed to parse resume.')

def handle_admin():
    st.success('Welcome to Admin Side')
    ad_user = st.text_input("Username")
    ad_password = st.text_input("Password", type='password')
    if st.button('Login'):
        if ad_user == 'Amigoes' and ad_password == 'Amigoes':
            st.success("Welcome Admin")
            try:
                cursor.execute("SELECT * FROM resume_data")
                data = cursor.fetchall()
                if data:
                    df = pd.DataFrame(data, columns=['ID', 'Name', 'Email', 'Resume Score', 'Timestamp',
                                                     'Total Page', 'Predicted Field', 'User Level',
                                                     'skills', 'Recommended Skills', 'Recommended Course'])
                    st.dataframe(df)
                    st.markdown(get_table_download_link(df, 'User_Data.csv', 'Download Report'), unsafe_allow_html=True)

                    st.subheader("📈 Pie Chart for Predicted Field Recommendations")
                    fig = px.pie(df, values=df['Predicted Field'].value_counts(),
                                 names=df['Predicted Field'].unique(), title='Predicted Field')
                    st.plotly_chart(fig)

                    st.subheader("📈 Pie Chart for User Experience Level")
                    fig = px.pie(df, values=df['User Level'].value_counts(),
                                 names=df['User Level'].unique(), title="User Experience Level")
                    st.plotly_chart(fig)
                else:
                    st.warning("No data found in the database")
            except pymysql.Error as e:
                st.error(f"Error fetching data: {e}")
        else:
            st.error("Wrong ID & Password Provided")

def run():
    st.title("Smart Resume Analyser")
    if connection:
        create_user_table()
    else:
        st.error("Could not connect to database.")

    st.sidebar.markdown("# Choose User")
    choice = st.sidebar.selectbox("Choose among the given options:", ["Normal User", "Admin"])
    img = Image.open('./Logo/SRA_Logo.jpg')
    img = img.resize((250, 250))
    st.image(img)

    if choice == 'Normal User':
        handle_normal_user()
    else:
        handle_admin()

# ✅ Run app
if __name__ == "__main__":
    run()
