# HOW TO RUN THIS APP:
# /Users/harry/Desktop/clg\ code\ tutor/.venv/bin/python -m streamlit run hackathon.py

import streamlit as st
import requests
import pandas as pd
import glob
import os
from datetime import date

# =========================
# CONFIG
# RapidAPI credentials
RAPIDAPI_KEY = "5bcd2fa2a3msh7139913b49958dcp17b189jsnfe308927250e"
RAPIDAPI_HOST = "jsearch.p.rapidapi.com"

# ZODIAC FEATURE
# =========================
def zodiac_sign(day, month):
    zodiac = [
        ("Capricorn", (12, 22), (1, 19), "Disciplined and always up for a challenge!"),
        ("Aquarius", (1, 20), (2, 18), "Inventive, quirky, and loves surprises!"),
        ("Pisces", (2, 19), (3, 20), "Dreamy, creative, and a bit mysterious!"),
        ("Aries", (3, 21), (4, 19), "Energetic, bold, and always first in line for fun!"),
        ("Taurus", (4, 20), (5, 20), "Reliable, loves snacks, and chill vibes!"),
        ("Gemini", (5, 21), (6, 20), "Chatty, curious, and always up for a new adventure!"),
        ("Cancer", (6, 21), (7, 22), "Caring, creative, and loves cozy hangouts!"),
        ("Leo", (7, 23), (8, 22), "Confident, fun-loving, and the life of the party!"),
        ("Virgo", (8, 23), (9, 22), "Organized, thoughtful, and a secret comedian!"),
        ("Libra", (9, 23), (10, 22), "Chill, friendly, and always up for a group activity!"),
        ("Scorpio", (10, 23), (11, 21), "Mysterious, passionate, and super loyal!"),
        ("Sagittarius", (11, 22), (12, 21), "Adventurous, optimistic, and loves exploring!")
    ]
    for sign, start, end, trait in zodiac:
        if (month == start[0] and day >= start[1]) or (month == end[0] and day <= end[1]):
            return sign, trait
    return "Unknown", "Just have fun!"

# =========================
# COURSE SUGGESTIONS
# =========================
COURSES = {
    "python": "Python for Everybody – Coursera",
    "sql": "SQL Bootcamp – Udemy",
    "excel": "Excel Skills for Business – Coursera",
    "javascript": "JavaScript Algorithms – freeCodeCamp",
    "react": "Meta Frontend Certificate – Coursera",
    "data": "Google Data Analytics – Coursera"
}

# =========================
# ROLE-BASED COURSES
# =========================

ROLE_COURSES = {
    "doctor": {
        "clinical knowledge": "Medical Education Platform – JAMA Network",
        "patient communication": "Interpersonal Skills – Udemy",
        "research": "Research Methods – Coursera",
        "diagnostics": "Medical Diagnostics – Udemy",
        "medical ethics": "Medical Ethics – edX"
    },
    "sportsperson": {
        "physical training": "Fitness Certification – NASM",
        "nutrition": "Sports Nutrition – Coursera",
        "mental resilience": "Mental Health Coaching – Udemy",
        "sport science": "Sport Science Basics – Coursera",
        "coaching": "Coaching Certification – ACE"
    },
    "media": {
        "content creation": "Content Strategy – Skillshare",
        "video editing": "Final Cut Pro & Adobe Premiere – Udemy",
        "social media": "Social Media Marketing – Coursera",
        "storytelling": "Storytelling Essentials – MasterClass",
        "analytics": "Google Analytics – Google Skills"
    },
    "teacher": {
        "classroom management": "Classroom Management – Coursera",
        "curriculum design": "Curriculum Design – edX",
        "edtech": "EdTech Tools – Udemy",
        "assessment": "Assessment Strategies – Coursera",
        "communication": "Effective Communication – LinkedIn Learning"
    },
    "lawyer": {
        "legal research": "Legal Research – Coursera",
        "contract law": "Contract Law – HarvardX",
        "negotiation": "Negotiation Skills – Coursera",
        "public speaking": "Public Speaking – Udemy",
        "ethics": "Legal Ethics – edX"
    },
    "architect": {
        "design principles": "Architectural Design – Coursera",
        "autocad": "AutoCAD Mastery – Udemy",
        "project management": "Project Management – Coursera",
        "sustainability": "Sustainable Design – edX",
        "presentation": "Design Presentation – LinkedIn Learning"
    },
    "chef": {
        "culinary skills": "Culinary Fundamentals – Coursera",
        "food safety": "Food Safety – Udemy",
        "menu design": "Menu Design – Skillshare",
        "nutrition": "Nutrition Basics – Coursera",
        "leadership": "Kitchen Leadership – LinkedIn Learning"
    },
    "artist": {
        "drawing": "Drawing Basics – Skillshare",
        "digital art": "Digital Art – Udemy",
        "portfolio": "Building a Portfolio – Coursera",
        "art history": "Art History – edX",
        "marketing": "Art Marketing – LinkedIn Learning"
    }
}

# =========================
# BACKEND CSV LOADING
# =========================
csv_files = [
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/efinancialcareers.csv",
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/glassdoor.csv",
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/indeed.csv",
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/jobstreet.csv",
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/mycareersfuture.csv",
    "/Users/harry/Downloads/drive-download-20260124T104629Z-1-001 2/prosple.csv"
]
csv_data = {}
for csv_path in csv_files:
    try:
        df = pd.read_csv(csv_path)
        csv_data[os.path.basename(csv_path)] = df
    except Exception as e:
        print(f"Failed to load {csv_path}: {e}")

# =========================
# SKILL MAPPING BY ROLE
# =========================
# OCCUPATIONS CSV LOADING (for scalability)
# CSV format: occupation,skills (comma-separated),roadmap (| separated: level:desc:salary),related (| separated)
OCCUPATIONS = {
    "Software Developer": {
        "desc": "Software developers design, build, and maintain computer programs and applications. They work with teams to solve problems, write code, test software, and continuously improve digital products for users in many industries.",
        "skills": ["Python", "JavaScript", "React", "SQL", "Git"],
        "roadmap": [
            {"level": "Entry", "desc": "Intern, Junior Developer", "salary": 35000},
            {"level": "Mid", "desc": "Developer, Engineer", "salary": 60000},
            {"level": "Senior", "desc": "Senior Dev, Lead", "salary": 90000}
        ],
        "related": ["Full-stack Developer", "Mobile Developer", "Cloud Architect", "AI Engineer"]
    },
    "Doctor": {
        "desc": "Doctors diagnose and treat illnesses, injuries, and other health conditions. They interact with patients, prescribe medications, perform procedures, and work in hospitals, clinics, or private practices to improve patient health.",
        "skills": ["Clinical Knowledge", "Patient Communication", "Research", "Diagnostics", "Medical Ethics"],
        "roadmap": [
            {"level": "Entry", "desc": "Resident, Junior Doctor", "salary": 50000},
            {"level": "Mid", "desc": "Doctor, Specialist", "salary": 100000},
            {"level": "Senior", "desc": "Consultant, Director", "salary": 180000}
        ],
        "related": ["Surgeon", "Medical Director", "Healthcare Administrator"]
    },
    "Teacher": {
        "desc": "Teachers educate students in schools or colleges, create lesson plans, deliver instruction, assess learning, and support student growth. They play a key role in shaping knowledge and skills for future success.",
        "skills": ["Classroom Management", "Curriculum Design", "EdTech", "Assessment", "Communication"],
        "roadmap": [
            {"level": "Entry", "desc": "Assistant Teacher", "salary": 30000},
            {"level": "Mid", "desc": "Teacher", "salary": 50000},
            {"level": "Senior", "desc": "Principal, Consultant", "salary": 80000}
        ],
        "related": ["School Principal", "Education Consultant", "Instructional Designer"]
    },
    "Civil Engineer": {
        "desc": "Civil engineers design, build, and supervise infrastructure projects like roads, bridges, and buildings. They ensure safety, sustainability, and efficiency in construction and public works.",
        "skills": ["AutoCAD", "Project Management", "Structural Analysis", "Surveying", "Construction Safety"],
        "roadmap": [
            {"level": "Entry", "desc": "Site Engineer, Junior Engineer", "salary": 35000},
            {"level": "Mid", "desc": "Project Engineer, Senior Engineer", "salary": 65000},
            {"level": "Senior", "desc": "Project Manager, Consultant", "salary": 100000}
        ],
        "related": ["Structural Engineer", "Construction Manager", "Urban Planner"]
    },
    "Nurse": {
        "desc": "Nurses provide patient care, administer medications, assist in procedures, and support doctors in hospitals and clinics. They are essential for patient recovery and health education.",
        "skills": ["Patient Care", "Medication Administration", "Critical Thinking", "Compassion", "Teamwork"],
        "roadmap": [
            {"level": "Entry", "desc": "Staff Nurse, Junior Nurse", "salary": 32000},
            {"level": "Mid", "desc": "Registered Nurse, Senior Nurse", "salary": 55000},
            {"level": "Senior", "desc": "Nurse Manager, Clinical Educator", "salary": 85000}
        ],
        "related": ["Nurse Practitioner", "Clinical Nurse Specialist", "Nurse Educator"]
    },
    "Accountant": {
        "desc": "Accountants manage financial records, prepare tax returns, analyze budgets, and ensure compliance with regulations. They work in businesses, government, or as independent professionals.",
        "skills": ["Financial Reporting", "Excel", "Taxation", "Auditing", "Analytical Skills"],
        "roadmap": [
            {"level": "Entry", "desc": "Accounts Assistant, Junior Accountant", "salary": 32000},
            {"level": "Mid", "desc": "Accountant, Senior Accountant", "salary": 55000},
            {"level": "Senior", "desc": "Finance Manager, Controller", "salary": 90000}
        ],
        "related": ["Auditor", "Financial Analyst", "Tax Consultant"]
    },
    "Graphic Designer": {
        "desc": "Graphic designers create visual content for print and digital media. They use design software to develop logos, advertisements, websites, and branding materials for clients or organizations.",
        "skills": ["Adobe Photoshop", "Illustrator", "Creativity", "Typography", "Branding"],
        "roadmap": [
            {"level": "Entry", "desc": "Junior Designer, Production Artist", "salary": 30000},
            {"level": "Mid", "desc": "Graphic Designer, Web Designer", "salary": 50000},
            {"level": "Senior", "desc": "Art Director, Creative Lead", "salary": 80000}
        ],
        "related": ["UI Designer", "Art Director", "Brand Manager"]
    },
    "Chef": {
        "desc": "Chefs plan menus, prepare meals, and manage kitchen staff in restaurants, hotels, or catering. They combine creativity and technique to deliver quality food experiences.",
        "skills": ["Culinary Skills", "Food Safety", "Menu Planning", "Time Management", "Creativity"],
        "roadmap": [
            {"level": "Entry", "desc": "Commis Chef, Line Cook", "salary": 25000},
            {"level": "Mid", "desc": "Sous Chef, Chef de Partie", "salary": 40000},
            {"level": "Senior", "desc": "Head Chef, Executive Chef", "salary": 70000}
        ],
        "related": ["Pastry Chef", "Catering Manager", "Food Stylist"]
    },
    "Sales Manager": {
        "desc": "Sales managers lead sales teams, set targets, develop strategies, and build client relationships. They analyze market trends and drive revenue growth for organizations.",
        "skills": ["Sales Strategy", "Negotiation", "CRM", "Leadership", "Market Analysis"],
        "roadmap": [
            {"level": "Entry", "desc": "Sales Executive, Sales Associate", "salary": 30000},
            {"level": "Mid", "desc": "Sales Supervisor, Account Manager", "salary": 55000},
            {"level": "Senior", "desc": "Sales Manager, Director", "salary": 95000}
        ],
        "related": ["Business Development Manager", "Key Account Manager", "Regional Sales Director"]
    },
    "Mechanical Engineer": {
        "desc": "Mechanical engineers design, develop, and test mechanical devices and systems. They work in industries like automotive, aerospace, manufacturing, and energy to solve technical challenges.",
        "skills": ["CAD", "Thermodynamics", "Problem Solving", "Project Management", "Mathematics"],
        "roadmap": [
            {"level": "Entry", "desc": "Junior Engineer, Design Engineer", "salary": 35000},
            {"level": "Mid", "desc": "Mechanical Engineer, Project Engineer", "salary": 65000},
            {"level": "Senior", "desc": "Lead Engineer, Engineering Manager", "salary": 110000}
        ],
        "related": ["Aerospace Engineer", "Manufacturing Engineer", "Maintenance Manager"]
    },
}
OCCUPATION_LIST = list(OCCUPATIONS.keys())
# =========================
# CAREER OPTIONS BY ROLE
# =========================
CAREER_OPTIONS = {
    "software developer": ["Full-stack Developer", "Mobile Developer", "Cloud Architect", "AI Engineer"],
    "data analyst": ["Business Analyst", "Financial Analyst", "Data Engineer", "Analytics Manager"],
    "product manager": ["Senior Product Manager", "Strategy Lead", "VP Product", "Startup Founder"],
    "ux designer": ["UI/UX Lead", "Design Manager", "Design System Lead", "UX Researcher"],
    "data scientist": ["ML Engineer", "Research Scientist", "AI Lead", "Analytics Manager"],
    "marketing analyst": ["Digital Marketing Manager", "Growth Lead", "Marketing Director", "Brand Manager"],
    "devops engineer": ["Cloud Architect", "Site Reliability Engineer", "Infrastructure Lead", "DevOps Manager"],
    "doctor": ["Specialist", "Surgeon", "Consultant", "Medical Director", "Healthcare Administrator"],
    "sportsperson": ["Professional Athlete", "Sports Coach", "Sports Manager", "Fitness Trainer", "Sports Scientist"],
    "media": ["Content Producer", "Video Director", "Social Media Manager", "Broadcast Journalist", "Digital Strategist"],
    "teacher": ["School Principal", "Curriculum Specialist", "Education Consultant", "Instructional Designer", "EdTech Trainer"],
    "lawyer": ["Corporate Lawyer", "Litigator", "Legal Advisor", "Judge", "Policy Analyst"],
    "architect": ["Urban Planner", "Interior Designer", "Project Architect", "Sustainability Consultant", "Design Director"],
    "chef": ["Head Chef", "Pastry Chef", "Food Stylist", "Culinary Instructor", "Restaurant Manager"],
    "artist": ["Illustrator", "Animator", "Gallery Curator", "Art Director", "Freelance Artist"],
}

# =========================
# UI HEADER
# =========================

st.title("Thrive")
st.subheader("Your personalized career roadmap")

st.divider()

# =========================
# SIDEBAR PROFILE
# =========================
with st.sidebar:
    st.header("👤 Profile")
    name = st.text_input("Name")
    dob = st.date_input("Birthdate", max_value=date.today(), value=date(2000, 1, 1), min_value=date(1960, 1, 1))
    role = st.selectbox("Occupation", OCCUPATION_LIST)
    location = st.selectbox("Location", ["Singapore"])
    available_skills = OCCUPATIONS[role]["skills"] if role else []
    skills = st.multiselect("Your Skills", available_skills)


# =========================
# JOB SEARCH VIA API
# =========================
st.header("Live Job Matches")

if st.button("Find Jobs"):
    with st.spinner("Fetching real jobs from market..."):
        url = "https://jsearch.p.rapidapi.com/search"
        
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST
        }
        
        params = {
            "query": f"{role if role else 'Software Engineer'} in {location}",
            "page": "1",
            "num_pages": "1"
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                jobs = data.get("data", [])

                if not jobs:
                    st.warning("No jobs found. Try refining role keywords.")
                else:
                    for job in jobs[:5]:  # Show top 5
                        with st.container(border=True):
                            st.subheader(job.get("job_title", "N/A"))
                            st.write(f"🏢 {job.get('employer_name', 'N/A')}")
                            st.write(f"📍 {job.get('job_country', 'N/A')}")
                            st.write(f"📝 {job.get('job_description', 'N/A')[:200]}...")
                            if job.get("job_apply_link"):
                                st.markdown(f"[Apply Here]({job['job_apply_link']})")
            elif response.status_code == 403:
                st.error("❌ API Key invalid or expired.")
            else:
                st.error(f"API Error: {response.status_code}. Check credentials.")
        except Exception as e:
            st.error(f"Connection Error: {str(e)}")

# =========================
# UPSKILLING ROADMAP
# =========================

st.header("Upskilling Recommendations")
UPSKILLING = {
    "Software Developer": [
        ("Python Mastery", "Python for Everybody – Coursera"),
        ("Web Development", "The Web Developer Bootcamp – Udemy"),
        ("System Design", "Grokking the System Design Interview – Educative"),
        ("Cloud Basics", "AWS Cloud Practitioner Essentials – AWS"),
        ("Git & Version Control", "Git Complete – Udemy")
    ],
    "Doctor": [
        ("Clinical Skills", "Clinical Skills Online – BMJ Learning"),
        ("Medical Research", "Understanding Medical Research – Coursera"),
        ("Patient Communication", "Interpersonal Skills – Udemy"),
        ("Diagnostics", "Medical Diagnostics – Udemy"),
        ("Medical Ethics", "Medical Ethics – edX")
    ],
    "Teacher": [
        ("Classroom Management", "Classroom Management – Coursera"),
        ("EdTech Tools", "EdTech Tools for Teachers – Udemy"),
        ("Assessment Strategies", "Assessment in Education – Coursera"),
        ("Curriculum Design", "Curriculum Design – edX"),
        ("Communication", "Effective Communication – LinkedIn Learning")
    ],
    "Civil Engineer": [
        ("AutoCAD", "AutoCAD Mastery – Udemy"),
        ("Project Management", "Project Management Principles – Coursera"),
        ("Structural Analysis", "Structural Engineering Basics – Udemy"),
        ("Construction Safety", "Construction Safety – edX"),
        ("Sustainability", "Sustainable Construction – Coursera")
    ],
    "Nurse": [
        ("Patient Care", "Patient Care Technician – Coursera"),
        ("Critical Thinking", "Critical Thinking in Nursing – Udemy"),
        ("Medication Administration", "Safe Medication Administration – Coursera"),
        ("Compassion in Care", "Compassionate Care – Udemy"),
        ("Teamwork", "Teamwork Skills – LinkedIn Learning")
    ],
    "Accountant": [
        ("Financial Reporting", "Financial Reporting – Coursera"),
        ("Excel Skills", "Excel Skills for Business – Coursera"),
        ("Taxation", "Taxation – Udemy"),
        ("Auditing", "Auditing I: Conceptual Foundations – Coursera"),
        ("Analytical Skills", "Business Analytics – Coursera")
    ],
    "Graphic Designer": [
        ("Photoshop", "Adobe Photoshop CC – Udemy"),
        ("Illustrator", "Adobe Illustrator CC – Udemy"),
        ("Typography", "Typography Fundamentals – Coursera"),
        ("Branding", "Brand Management – Coursera"),
        ("Creativity", "Creative Thinking – LinkedIn Learning")
    ],
    "Chef": [
        ("Culinary Skills", "Culinary Fundamentals – Coursera"),
        ("Food Safety", "Food Safety – Udemy"),
        ("Menu Planning", "Menu Design – Skillshare"),
        ("Time Management", "Time Management for Chefs – Udemy"),
        ("Creativity", "Creative Cooking – Coursera")
    ],
    "Sales Manager": [
        ("Sales Strategy", "Sales Strategies – Coursera"),
        ("Negotiation", "Successful Negotiation – Coursera"),
        ("CRM", "CRM Fundamentals – Udemy"),
        ("Leadership", "Leadership Skills – LinkedIn Learning"),
        ("Market Analysis", "Market Research – Coursera")
    ],
    "Mechanical Engineer": [
        ("CAD", "CAD and Digital Manufacturing – Coursera"),
        ("Thermodynamics", "Thermodynamics – edX"),
        ("Project Management", "Project Management for Engineers – Coursera"),
        ("Problem Solving", "Engineering Problem Solving – Udemy"),
        ("Mathematics", "Engineering Mathematics – Coursera")
    ]
}

if role:
    recos = UPSKILLING.get(role, [])
    # Remove upskilling recos for skills the user already has
    user_skills_lower = [s.lower() for s in skills]
    filtered_recos = [(skill, course) for skill, course in recos if skill.lower() not in user_skills_lower]
    if filtered_recos:
        st.info(f"💡 Based on your role as **{role}**, here are recommended upskilling courses:")
        for skill, course in filtered_recos:
            st.success(f"🔹 **{skill}** → {course}")
    else:
        st.success("🌟 You're well-equipped! Focus on applications and hands-on projects.")
else:
    st.info("👉 Enter a target role above to get personalized upskilling recommendations!")

# =========================
# APPLICATION TRACKER
# =========================
st.header("Application Tracker")

if "apps" not in st.session_state:
    st.session_state.apps = []

col1, col2 = st.columns([3, 1])
with col1:
    job_name = st.text_input("Job Title & Company")
with col2:
    if st.button("+ Add", use_container_width=True):
        if job_name:
            st.session_state.apps.append({"job": job_name, "status": "Applied", "date": str(date.today())})
            st.success("✅ Application added!")

if st.session_state.apps:
    st.markdown("### Your Applications")
    for idx, app in enumerate(st.session_state.apps):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"**{app['job']}**")
            st.caption(f"Applied on {app['date']}")
        with col2:
            status_options = ["Applied", "Interview", "Offer", "Rejected", "Pending"]
            new_status = st.selectbox(f"Status {idx}", status_options, index=status_options.index(app['status']), label_visibility="collapsed")
            st.session_state.apps[idx]["status"] = new_status
        with col3:
            if st.button("🗑️", key=f"del_{idx}"):
                st.session_state.apps.pop(idx)
                st.rerun()
else:
    st.info("📍 No applications yet. Start tracking your applications here!")

# =========================
# CAREER INSIGHT



# =========================
# FUN FACT (Zodiac Output)
# =========================
st.header("Fun Fact")
ZODIAC_CAREER_ADVICE = {
    "Aries": {
        "default": "Your boldness and drive help you take initiative and lead projects.",
        "Software Developer": "Your energy and determination help you tackle complex coding challenges head-on.",
        "Doctor": "Your decisiveness and courage are assets in high-pressure medical situations.",
        "Teacher": "Your enthusiasm inspires students and keeps the classroom dynamic.",
        "Civil Engineer": "Your pioneering spirit is perfect for managing large-scale projects.",
        "Nurse": "Your quick action and resilience are vital in patient care.",
        "Accountant": "Your focus and drive help you meet deadlines and solve financial puzzles.",
        "Graphic Designer": "Your bold ideas set trends in visual design.",
        "Chef": "Your competitive edge pushes you to create standout dishes.",
        "Sales Manager": "Your assertiveness helps you close deals and motivate your team.",
        "Mechanical Engineer": "Your initiative leads to innovative engineering solutions."
    },
    "Taurus": {
        "default": "Your reliability and patience make you a steady force in any team.",
        "Software Developer": "Your persistence helps you debug and optimize code with care.",
        "Doctor": "Your calm and steady approach reassures patients and colleagues alike.",
        "Teacher": "Your patience supports students' learning at every pace.",
        "Civil Engineer": "Your attention to detail ensures safe, lasting structures.",
        "Nurse": "Your nurturing nature comforts patients in need.",
        "Accountant": "Your methodical work style ensures financial accuracy.",
        "Graphic Designer": "Your appreciation for beauty shines in your creative work.",
        "Chef": "Your consistency delivers quality in every meal.",
        "Sales Manager": "Your dependability builds trust with clients.",
        "Mechanical Engineer": "Your practical mindset leads to robust engineering designs."
    },
    "Gemini": {
        "default": "Your adaptability and communication skills open many doors.",
        "Software Developer": "Your curiosity keeps you learning new technologies.",
        "Doctor": "Your communication skills help you connect with patients and peers.",
        "Teacher": "Your versatility makes lessons engaging and accessible.",
        "Civil Engineer": "Your adaptability helps you manage changing project needs.",
        "Nurse": "Your quick thinking is invaluable in fast-paced environments.",
        "Accountant": "Your analytical mind helps you spot trends and anomalies.",
        "Graphic Designer": "Your creativity and flexibility lead to fresh, innovative designs.",
        "Chef": "Your openness to new ideas inspires creative menus.",
        "Sales Manager": "Your people skills help you build strong client relationships.",
        "Mechanical Engineer": "Your curiosity drives you to explore new engineering solutions."
    },
    "Cancer": {
        "default": "Your empathy and intuition make you a supportive colleague.",
        "Software Developer": "Your intuition helps you anticipate user needs in software design.",
        "Doctor": "Your compassion is a comfort to patients and families.",
        "Teacher": "Your caring nature creates a nurturing classroom environment.",
        "Civil Engineer": "Your sense of responsibility ensures community-focused projects.",
        "Nurse": "Your empathy is at the heart of excellent patient care.",
        "Accountant": "Your loyalty makes you a trusted advisor.",
        "Graphic Designer": "Your sensitivity to emotion enhances your visual storytelling.",
        "Chef": "Your care for others is reflected in your food.",
        "Sales Manager": "Your intuition helps you understand client needs.",
        "Mechanical Engineer": "Your dedication ensures every detail is considered."
    },
    "Leo": {
        "default": "Your confidence and leadership inspire those around you.",
        "Software Developer": "Your leadership helps guide development teams to success.",
        "Doctor": "Your presence reassures patients and leads medical teams.",
        "Teacher": "Your charisma makes learning memorable for students.",
        "Civil Engineer": "Your vision brings ambitious projects to life.",
        "Nurse": "Your positivity uplifts your team and patients.",
        "Accountant": "Your confidence helps you present financial insights clearly.",
        "Graphic Designer": "Your bold style makes your work stand out.",
        "Chef": "Your flair brings creativity to the kitchen.",
        "Sales Manager": "Your enthusiasm motivates your sales team.",
        "Mechanical Engineer": "Your leadership drives engineering projects forward."
    },
    "Virgo": {
        "default": "Your attention to detail and organization are your superpowers.",
        "Software Developer": "Your precision ensures clean, efficient code.",
        "Doctor": "Your analytical skills support accurate diagnoses.",
        "Teacher": "Your organization keeps the classroom running smoothly.",
        "Civil Engineer": "Your meticulous planning ensures project success.",
        "Nurse": "Your careful approach ensures patient safety.",
        "Accountant": "Your accuracy is key to financial integrity.",
        "Graphic Designer": "Your eye for detail perfects every design.",
        "Chef": "Your methodical work ensures consistent results.",
        "Sales Manager": "Your organization keeps your team on track.",
        "Mechanical Engineer": "Your thoroughness leads to reliable engineering solutions."
    },
    "Libra": {
        "default": "Your sense of balance and fairness makes you a great team player.",
        "Software Developer": "Your collaborative spirit helps teams work in harmony.",
        "Doctor": "Your diplomacy helps resolve conflicts in healthcare settings.",
        "Teacher": "Your fairness creates an inclusive classroom.",
        "Civil Engineer": "Your sense of balance is ideal for project management.",
        "Nurse": "Your tact helps you navigate sensitive situations.",
        "Accountant": "Your objectivity ensures unbiased financial advice.",
        "Graphic Designer": "Your sense of harmony enhances your compositions.",
        "Chef": "Your balanced approach creates well-rounded menus.",
        "Sales Manager": "Your negotiation skills close deals smoothly.",
        "Mechanical Engineer": "Your fairness fosters strong team collaboration."
    },
    "Scorpio": {
        "default": "Your focus and determination help you master any challenge.",
        "Software Developer": "Your intensity drives you to solve the toughest bugs.",
        "Doctor": "Your determination is vital in complex medical cases.",
        "Teacher": "Your passion inspires students to dig deeper.",
        "Civil Engineer": "Your resourcefulness overcomes project obstacles.",
        "Nurse": "Your commitment ensures the best patient outcomes.",
        "Accountant": "Your investigative mind uncovers financial insights.",
        "Graphic Designer": "Your depth brings meaning to your designs.",
        "Chef": "Your passion elevates your culinary creations.",
        "Sales Manager": "Your drive helps you exceed targets.",
        "Mechanical Engineer": "Your persistence leads to breakthrough innovations."
    },
    "Sagittarius": {
        "default": "Your optimism and love of learning open new horizons.",
        "Software Developer": "Your curiosity keeps you exploring new tech trends.",
        "Doctor": "Your adventurous spirit helps you adapt to new medical advances.",
        "Teacher": "Your enthusiasm makes learning an adventure for students.",
        "Civil Engineer": "Your big-picture thinking inspires innovative designs.",
        "Nurse": "Your positivity supports patients through recovery.",
        "Accountant": "Your open mind helps you adapt to changing regulations.",
        "Graphic Designer": "Your adventurous style leads to unique visuals.",
        "Chef": "Your love of discovery brings global flavors to your kitchen.",
        "Sales Manager": "Your optimism energizes your team and clients.",
        "Mechanical Engineer": "Your vision leads to creative engineering solutions."
    },
    "Capricorn": {
        "default": "Your discipline and ambition drive you to achieve your goals.",
        "Software Developer": "Your work ethic helps you master complex systems.",
        "Doctor": "Your discipline supports years of medical training.",
        "Teacher": "Your ambition inspires students to aim high.",
        "Civil Engineer": "Your persistence ensures projects are completed on time.",
        "Nurse": "Your reliability makes you a pillar of your team.",
        "Accountant": "Your diligence ensures financial accuracy.",
        "Graphic Designer": "Your determination builds a strong design portfolio.",
        "Chef": "Your ambition drives you to culinary excellence.",
        "Sales Manager": "Your discipline keeps your team focused on results.",
        "Mechanical Engineer": "Your perseverance leads to engineering success."
    },
    "Aquarius": {
        "default": "Your originality and vision spark innovation.",
        "Software Developer": "Your innovative ideas lead to creative software solutions.",
        "Doctor": "Your forward-thinking approach embraces new medical technologies.",
        "Teacher": "Your unique teaching style engages students in new ways.",
        "Civil Engineer": "Your inventive mind brings fresh perspectives to projects.",
        "Nurse": "Your open-mindedness helps you adapt to new care methods.",
        "Accountant": "Your analytical skills uncover new financial strategies.",
        "Graphic Designer": "Your originality sets your designs apart.",
        "Chef": "Your creativity inspires innovative dishes.",
        "Sales Manager": "Your unconventional approach opens new markets.",
        "Mechanical Engineer": "Your vision leads to cutting-edge engineering."
    },
    "Pisces": {
        "default": "Your creativity and intuition help you connect with others.",
        "Software Developer": "Your imagination helps you design user-friendly software.",
        "Doctor": "Your empathy supports compassionate patient care.",
        "Teacher": "Your creativity makes learning memorable.",
        "Civil Engineer": "Your intuition guides you in solving complex problems.",
        "Nurse": "Your compassion comforts patients and families.",
        "Accountant": "Your intuition helps you see the story behind the numbers.",
        "Graphic Designer": "Your artistic vision brings beauty to your work.",
        "Chef": "Your creativity inspires new recipes and flavors.",
        "Sales Manager": "Your empathy helps you understand client needs.",
        "Mechanical Engineer": "Your imagination leads to innovative designs."
    }
}

if dob and role:
    sign, trait = zodiac_sign(dob.day, dob.month)
    advice = ZODIAC_CAREER_ADVICE.get(sign, {}).get(role, None)
    if not advice:
        advice = ZODIAC_CAREER_ADVICE.get(sign, {}).get("default", trait)
    st.info(f"♈ {name+', ' if name else ''}as a **{sign}**, {advice}")
elif dob:
    sign, trait = zodiac_sign(dob.day, dob.month)
    st.info(f"♈ Zodiac: **{sign}** — {trait}")
# =========================
st.header("Career Insights & Roadmap")
if role:
    occ = OCCUPATIONS[role]
    st.subheader(f"About {role}")
    st.write(occ["desc"])
    st.subheader(f"Roadmap for {role}")
    for step in occ["roadmap"]:
        st.write(f"**{step['level']}**: {step['desc']} | Starting Salary: ${step['salary']:,}")
    st.info(f"Key Skills: {', '.join(occ['skills'])}")
    if occ["related"]:
        st.markdown(f"**Related Careers:** {', '.join(occ['related'])}")
else:
    st.write("🚀 Welcome to Thrive! Enter your details above to get started.")

