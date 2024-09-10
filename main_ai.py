from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
from openai import OpenAI
import base64
import os
import logging
import uuid
import shutil
from datetime import datetime
import random

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)

my_key = "*********************************"
client = OpenAI(api_key=my_key)

message_history = {}
job_description = ""
question_count = {}
interview_completed = {}

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'cvs'))
    os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

interview_sessions = {}
candidates = {}


@app.route('/')
def home():
    job_title = request.args.get('job_title')
    if not job_title:
        return "Invalid interview link. Please contact the HR department.", 400
    return render_template('index.html', job_title=job_title)


@app.route('/company')
def company_interface():
    return render_template('company_interface.html')


@app.route('/upload_job_description', methods=['POST'])
def upload_job_description():
    job_title = request.form['job_title']
    file = request.files['file']
    if file:
        filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
        file.save(filename)
        return jsonify({"message": "Job description uploaded successfully."})
    return jsonify({"error": "No file uploaded"}), 400


@app.route('/get_job_description/<job_title>')
def get_job_description(job_title):
    filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
    try:
        with open(filename, 'r') as f:
            content = f.read()
        return jsonify({"content": content})
    except FileNotFoundError:
        return jsonify({"error": "Job description not found"}), 404


@app.route('/get_candidates/<job_title>')
def get_candidates(job_title):
    candidates_list = [
        {**candidate, 'passed': get_candidate_status(job_title, candidate['candidate_id'])}
        for candidate in candidates.values()
        if candidate['job_title'] == job_title
    ]
    return jsonify({"candidates": candidates_list})


@app.route('/create_interview_link/<job_title>', methods=['POST'])
def create_interview_link(job_title):
    interview_url = url_for('home', job_title=job_title, _external=True)
    return jsonify({"interview_url": interview_url})


@app.route('/download_cv/<candidate_id>')
def download_cv(candidate_id):
    if candidate_id in candidates:
        cv_filename = candidates[candidate_id]['cv_filename']
        cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
        return send_file(cv_path, as_attachment=True)
    return "CV not found", 404


@app.route('/download_report/<job_title>/<candidate_id>')
def download_report(job_title, candidate_id):
    report_filename = f"report_{candidate_id}.txt"
    report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
    if os.path.exists(report_path):
        return send_file(report_path, as_attachment=True)
    return "Report not found", 404


@app.route('/view_report/<job_title>/<candidate_id>')
def view_report(job_title, candidate_id):
    logging.debug(f"Attempting to view report for job: {job_title}, candidate: {candidate_id}")
    report_filename = f"report_{candidate_id}.txt"
    report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
    logging.debug(f"Looking for report at: {report_path}")

    if os.path.exists(report_path):
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
            logging.debug(f"Report found and read: {report_content[:100]}...")  # Log the first 100 characters
            return jsonify({"report": report_content})
        except Exception as e:
            logging.error(f"Error reading report: {str(e)}")
            return jsonify({"error": f"Error reading report: {str(e)}"}), 500
    else:
        logging.error(f"Report not found at {report_path}")
        return jsonify({"error": "Report not found"}), 404


@app.route('/delete_candidate/<job_title>/<candidate_id>', methods=['POST'])
def delete_candidate(job_title, candidate_id):
    if candidate_id in candidates:
        del candidates[candidate_id]
        cv_filename = f"{candidate_id}_CV.pdf"
        cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
        if os.path.exists(cv_path):
            os.remove(cv_path)
        report_filename = f"report_{candidate_id}.txt"
        report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
        if os.path.exists(report_path):
            os.remove(report_path)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Candidate not found"}), 404


@app.route('/register_candidate', methods=['POST'])
def register_candidate():
    try:
        full_name = request.form['full_name']
        email = request.form['email']
        phone = request.form.get('phone', '')
        job_title = request.form['job_title']
        cv_file = request.files['cv']

        # Check if the job exists
        job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
        if not os.path.exists(job_file):
            return jsonify({"error": f"Job description for '{job_title}' does not exist"}), 400

        # Generate Candidate ID
        name_parts = full_name.split(' ')
        if len(name_parts) < 2:
            first_name = name_parts[0]
            last_name = "Unknown"
        else:
            first_name = name_parts[0]
            last_name = ' '.join(name_parts[1:])

        id_prefix = f"{first_name[:2].upper()}-{last_name[:2].upper()}"
        id_suffix = phone[-4:] if phone else ''.join([str(random.randint(0, 9)) for _ in range(4)])
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        candidate_id = f"{id_prefix}-{id_suffix}-{timestamp}"

        # Save CV
        cv_filename = f"{candidate_id}_CV.pdf"
        cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
        os.makedirs(os.path.dirname(cv_path), exist_ok=True)
        cv_file.save(cv_path)

        # Store candidate information
        candidates[candidate_id] = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'job_title': job_title,
            'cv_filename': cv_filename,
            'candidate_id': candidate_id
        }

        # Create interview session
        session_id = str(uuid.uuid4())
        interview_sessions[session_id] = {
            "job_title": job_title,
            "candidate_id": candidate_id,
            "started": False
        }

        return jsonify({"session_id": session_id, "candidate_id": candidate_id})
    except Exception as e:
        app.logger.error(f"Error in register_candidate: {str(e)}")
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500


@app.route('/interview/<session_id>')
def interview(session_id):
    if session_id not in interview_sessions:
        return "Invalid interview session", 404
    job_title = interview_sessions[session_id]["job_title"]
    candidate_id = interview_sessions[session_id]["candidate_id"]
    return render_template('index.html', session_id=session_id, job_title=job_title, candidate_id=candidate_id)


@app.route('/start_interview', methods=['POST'])
def start_interview():
    session_id = request.form.get('session_id')
    job_title = request.form.get('job_title')
    candidate_id = request.form.get('candidate_id')

    if not session_id or not job_title or not candidate_id:
        return jsonify({"error": "Missing session_id, job_title, or candidate_id"}), 400

    if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
        return jsonify({"error": "Invalid or already started session"}), 400

    filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
    try:
        with open(filename, 'r') as f:
            job_description = f.read()
    except FileNotFoundError:
        return jsonify({"error": "Job description not found"}), 404

    question_count[session_id] = 0
    interview_completed[session_id] = False
    message_history[session_id] = []

    candidate_name = candidates[candidate_id]['full_name']
    system_message = f"""
    You are an AI HR interviewer. Your task is to conduct an interview for {candidate_name} based on the following job description:
    {job_description}

    Follow these guidelines:
    1. Your name is "Maya"
    2. your answer should not be more longer than 25-30 words.
    2. The location of the position is Netanya not Tel Aviv, dont confuse.
    2. Start with a formal but polite greeting. Introduce yourself as an AI HR interviewer for the company mentioned in the job description.txt file learn this file well.
    3. Critical! : Don't make mistakes in the company name or location of the position! Do double check with the job description.txt file.
    4. this is example of good first massage : "AI: Hello Yonatan,  I'm Maya, an AI HR interviewer for Google. We're glad to have you here for the interview for the Data Analyst position at our office in Netanya.  Are you ready to begin the interview?" " 
     - this is general idea of how to start in the first massage..(The first name and the position from the job description.txt file and may change).
    5. Inform the candidate about the position they're interviewing for.
    6. Ask if they're ready to begin the interview.
    7. Conduct the interview naturally, as a real HR professional would:
    - Ask questions one at a time, without mentioning their purpose or labeling them.
    - Start by asking about the candidate's current location.
    - Internally assess the location's suitability:
    note : when you ask and check candidate that you cant write it down relatively far and speak relative rather than in exact time and also Do not offer or ask about relocation, just listen to their opinion on how they will deal with it.
      a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
      b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
      c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role. 
    - Inquire about educational background relevant to the position.
    - Ask about professional experience related to the role.

    8. Internally assess candidate suitability based on responses in three categories:
    - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
    - Educational: Evaluate qualifications against requirements.
    - Professional: Assess relevant work experience.
    Mark each area as high, medium, or low suitability without informing the candidate.

    9. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.

    10. You have a total of 5 questions for the entire interview.
    11. important: If a candidate's answer is unclear, you may ask and need to ask for clarification once per question.
    12. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
    13. Do not provide any assessment or report at the end of the interview.
    14. Maintain a neutral, professional tone throughout.
    15. Do not reveal assessments or provide feedback on responses.
    16. Transition between questions naturally without numbering or explaining their purpose.
    """

    message_history[session_id].append({"role": "system", "content": system_message})
    initial_greeting = get_chatgpt_response("Start the interview with a greeting and introduction.", session_id)
    audio_data = text_to_speech_openai(initial_greeting)
    audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None

    interview_sessions[session_id]["started"] = True

    return jsonify({"message": initial_greeting, "audio": audio_base64})


@app.route('/send_message', methods=['POST'])
def send_message():
    user_message = request.form['message']
    session_id = request.form['session_id']

    if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
        return jsonify({"error": "Invalid or not started session"}), 400

    if interview_completed.get(session_id, False):
        return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
                        "interview_completed": True})

    if question_count[session_id] < 8:
        ai_response = get_chatgpt_response(user_message, session_id)
        question_count[session_id] += 1
    else:
        ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.",
                                           session_id)
        interview_completed[session_id] = True
        # Automatically generate report
        report, passed = generate_report(session_id)
        logging.debug(f"Interview completed for session {session_id}. Report generated: {report[:100]}...")

    audio_data = text_to_speech_openai(ai_response)
    audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None

    return jsonify({
        "message": ai_response,
        "audio": audio_base64,
        "interview_completed": interview_completed.get(session_id, False)
    })


def generate_report(session_id):
    logging.debug(f"Generating report for session {session_id}")

    job_title = interview_sessions[session_id]["job_title"]
    candidate_id = interview_sessions[session_id]["candidate_id"]
    candidate = candidates[candidate_id]

    report_prompt = f"""
    You are an AI HR assistant tasked with evaluating {candidate['full_name']} (ID: {candidate_id}) based on their interview for the position of {job_title} at Amazon. Review the entire conversation above and provide a detailed assessment including:

    1. An executive summary with an overall pass/fail decision and key strengths.
    2. Detailed assessments of:
       - Geographical compatibility
       - Educational background
       - Professional experience
    3. Interview insights
    4. Potential areas for growth
    5. A conclusion with a final decision

    Present this information in the following format:

    [Amazon Logo]

    CANDIDATE EVALUATION REPORT
    ===========================

    Candidate: [Full Name] (ID: [Candidate ID])
    Position: [Job Title]
    Interview Date: [Current Date]

    EXECUTIVE SUMMARY
    -----------------
    OVERALL DECISION: [PASS/FAIL] [✅/❌]

    🏆 Recommendation: [Your recommendation]
    🎯 Overall Fit: [Your assessment]
    🚀 Key Strength: [Main strength]

        DETAILED ASSESSMENT
        -------------------

        📍 Geographical Compatibility
           Status: [Your assessment]
           • [Key points]

        🎓 Educational Background
           Status: [Your assessment]
           • [Key points]

        💼 Professional Experience
           Status: [Your assessment]
           • [Key points]

        INTERVIEW INSIGHTS
        ------------------
        • [Key insights from the interview]

        POTENTIAL AREAS FOR GROWTH
        --------------------------
        • [Areas for improvement or development]

        CONCLUSION
        ----------
        [A paragraph summarizing the candidate's fit and potential]

        FINAL DECISION: [PASS/FAIL] [✅/❌]
        [Final recommendation]

        [AI Interviewer Signature]
        Maya
        AI HR Interviewer
        Amazon

        Important: Make sure to base your assessment solely on the information provided in the interview conversation. If certain details are missing, make reasonable assumptions and note them in your report.
        """

    message_history[session_id].append({"role": "user", "content": report_prompt})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=message_history[session_id]
    )
    report = response.choices[0].message.content.strip()

    # Determine if the candidate passed
    passed = "PASS" in report.split("OVERALL DECISION:")[-1].split("\n")[0]

    # Save the report to a text file
    report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
    if not os.path.exists(report_folder):
        os.makedirs(report_folder)
    report_filename = f"report_{candidate_id}.txt"
    report_path = os.path.join(report_folder, report_filename)
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        logging.debug(f"Report saved to {report_path}")

        # Update candidate information with report filename
        candidates[candidate_id]['report_filename'] = report_filename

    except Exception as e:
        logging.error(f"Error saving report to file: {e}")

    return report, passed


def get_candidate_status(job_title, candidate_id):
    report_filename = f"report_{candidate_id}.txt"
    report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
    if os.path.exists(report_path):
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
            return "PASS" in content.split("FINAL DECISION:")[-1].split("\n")[0]
    return False


@app.route('/get_all_job_descriptions')
def get_all_job_descriptions():
    job_descriptions = []
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.endswith('.txt'):
            job_title = filename[:-4]  # Remove .txt extension
            job_descriptions.append({"title": job_title, "file_name": filename})
    return jsonify({"job_descriptions": job_descriptions})


@app.route('/delete_job/<job_title>', methods=['POST'])
def delete_job(job_title):
    job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
    report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)

    try:
        if os.path.exists(job_file):
            os.remove(job_file)
        if os.path.exists(report_folder):
            shutil.rmtree(report_folder)
        # Remove candidates associated with this job
        candidates_to_remove = [cid for cid, c in candidates.items() if c['job_title'] == job_title]
        for cid in candidates_to_remove:
            del candidates[cid]
        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Error deleting job {job_title}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def get_chatgpt_response(question, session_id):
    message_history[session_id].append({"role": "user", "content": question})
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=message_history[session_id]
    )
    chat_response = response.choices[0].message.content.strip()
    message_history[session_id].append({"role": "assistant", "content": chat_response})
    return chat_response


def text_to_speech_openai(text):
    response = client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=text
    )
    return response.content


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

















































# from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
# from openai import OpenAI
# import base64
# import os
# import logging
# import uuid
# import shutil
# from datetime import datetime
# import random
#
# app = Flask(__name__)
#
# logging.basicConfig(level=logging.DEBUG)
#
# my_key = "sk-proj-86fpKmKwBlTjtdKk5JdAT3BlbkFJ05rqWxMargDkMwMH2CRJ"
# client = OpenAI(api_key=my_key)
#
# message_history = {}
# job_description = ""
# question_count = {}
# interview_completed = {}
#
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'cvs'))
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#
# interview_sessions = {}
# candidates = {}
#
#
# @app.route('/')
# def home():
#     job_title = request.args.get('job_title')
#     if not job_title:
#         return "Invalid interview link. Please contact the HR department.", 400
#     return render_template('index.html', job_title=job_title)
#
#
# @app.route('/company')
# def company_interface():
#     return render_template('company_interface.html')
#
#
# @app.route('/upload_job_description', methods=['POST'])
# def upload_job_description():
#     job_title = request.form['job_title']
#     file = request.files['file']
#     if file:
#         filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         file.save(filename)
#         return jsonify({"message": "Job description uploaded successfully."})
#     return jsonify({"error": "No file uploaded"}), 400
#
#
# @app.route('/get_job_description/<job_title>')
# def get_job_description(job_title):
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             content = f.read()
#         return jsonify({"content": content})
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#
# @app.route('/get_candidates/<job_title>')
# def get_candidates(job_title):
#     candidates_list = [
#         {**candidate, 'passed': get_candidate_status(job_title, candidate['candidate_id'])}
#         for candidate in candidates.values()
#         if candidate['job_title'] == job_title
#     ]
#     return jsonify({"candidates": candidates_list})
#
#
# @app.route('/create_interview_link/<job_title>', methods=['POST'])
# def create_interview_link(job_title):
#     interview_url = url_for('home', job_title=job_title, _external=True)
#     return jsonify({"interview_url": interview_url})
#
#
# @app.route('/download_cv/<candidate_id>')
# def download_cv(candidate_id):
#     if candidate_id in candidates:
#         cv_filename = candidates[candidate_id]['cv_filename']
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         return send_file(cv_path, as_attachment=True)
#     return "CV not found", 404
#
#
# @app.route('/download_report/<job_title>/<candidate_id>')
# def download_report(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         return send_file(report_path, as_attachment=True)
#     return "Report not found", 404
#
#
# @app.route('/view_report/<job_title>/<candidate_id>')
# def view_report(job_title, candidate_id):
#     logging.debug(f"Attempting to view report for job: {job_title}, candidate: {candidate_id}")
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     logging.debug(f"Looking for report at: {report_path}")
#
#     if os.path.exists(report_path):
#         try:
#             with open(report_path, 'r', encoding='utf-8') as f:
#                 report_content = f.read()
#             logging.debug(f"Report found and read: {report_content[:100]}...")  # Log the first 100 characters
#             return jsonify({"report": report_content})
#         except Exception as e:
#             logging.error(f"Error reading report: {str(e)}")
#             return jsonify({"error": f"Error reading report: {str(e)}"}), 500
#     else:
#         logging.error(f"Report not found at {report_path}")
#         return jsonify({"error": "Report not found"}), 404
#
#
# @app.route('/delete_candidate/<job_title>/<candidate_id>', methods=['POST'])
# def delete_candidate(job_title, candidate_id):
#     if candidate_id in candidates:
#         del candidates[candidate_id]
#         cv_filename = f"{candidate_id}_CV.pdf"
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         if os.path.exists(cv_path):
#             os.remove(cv_path)
#         report_filename = f"report_{candidate_id}.txt"
#         report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#         if os.path.exists(report_path):
#             os.remove(report_path)
#         return jsonify({"success": True})
#     return jsonify({"success": False, "error": "Candidate not found"}), 404
#
#
# @app.route('/register_candidate', methods=['POST'])
# def register_candidate():
#     try:
#         full_name = request.form['full_name']
#         email = request.form['email']
#         phone = request.form.get('phone', '')
#         job_title = request.form['job_title']
#         cv_file = request.files['cv']
#
#         # Check if the job exists
#         job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         if not os.path.exists(job_file):
#             return jsonify({"error": f"Job description for '{job_title}' does not exist"}), 400
#
#         # Generate Candidate ID
#         name_parts = full_name.split(' ')
#         if len(name_parts) < 2:
#             first_name = name_parts[0]
#             last_name = "Unknown"
#         else:
#             first_name = name_parts[0]
#             last_name = ' '.join(name_parts[1:])
#
#         id_prefix = f"{first_name[:2].upper()}-{last_name[:2].upper()}"
#         id_suffix = phone[-4:] if phone else ''.join([str(random.randint(0, 9)) for _ in range(4)])
#         timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#         candidate_id = f"{id_prefix}-{id_suffix}-{timestamp}"
#
#         # Save CV
#         cv_filename = f"{candidate_id}_CV.pdf"
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         os.makedirs(os.path.dirname(cv_path), exist_ok=True)
#         cv_file.save(cv_path)
#
#         # Store candidate information
#         candidates[candidate_id] = {
#             'full_name': full_name,
#             'email': email,
#             'phone': phone,
#             'job_title': job_title,
#             'cv_filename': cv_filename,
#             'candidate_id': candidate_id
#         }
#
#         # Create interview session
#         session_id = str(uuid.uuid4())
#         interview_sessions[session_id] = {
#             "job_title": job_title,
#             "candidate_id": candidate_id,
#             "started": False
#         }
#
#         return jsonify({"session_id": session_id, "candidate_id": candidate_id})
#     except Exception as e:
#         app.logger.error(f"Error in register_candidate: {str(e)}")
#         return jsonify({"error": f"Registration failed: {str(e)}"}), 500
#
#
# @app.route('/interview/<session_id>')
# def interview(session_id):
#     if session_id not in interview_sessions:
#         return "Invalid interview session", 404
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     return render_template('index.html', session_id=session_id, job_title=job_title, candidate_id=candidate_id)
#
#
# @app.route('/start_interview', methods=['POST'])
# def start_interview():
#     session_id = request.form.get('session_id')
#     job_title = request.form.get('job_title')
#     candidate_id = request.form.get('candidate_id')
#
#     if not session_id or not job_title or not candidate_id:
#         return jsonify({"error": "Missing session_id, job_title, or candidate_id"}), 400
#
#     if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or already started session"}), 400
#
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             job_description = f.read()
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#     question_count[session_id] = 0
#     interview_completed[session_id] = False
#     message_history[session_id] = []
#
#     candidate_name = candidates[candidate_id]['full_name']
#     system_message = f"""
#     You are an AI HR interviewer. Your task is to conduct an interview for {candidate_name} based on the following job description:
#     {job_description}
#
#     Follow these guidelines:
#     1. Your name is "Maya"
#     2. Start with a formal but polite greeting. Introduce yourself as an AI HR interviewer for the company mentioned in the job description.txt file learn this file well.
#     3. Don't make mistakes in the company name or location of the position! Do double check with the job description.txt file.
#     4. Inform the candidate about the position they're interviewing for.
#     5. Ask if they're ready to begin the interview.
#     6. Conduct the interview naturally, as a real HR professional would:
#     - Ask questions one at a time, without mentioning their purpose or labeling them.
#     - Start by asking about the candidate's current location.
#     - Internally assess the location's suitability:
#     note : when you ask and check candidate that you cant write it down relatively far and speak relative rather than in exact time and also Do not offer or ask about relocation, just listen to their opinion on how they will deal with it.
#       a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
#       b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
#       c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role.
#     - Inquire about educational background relevant to the position.
#     - Ask about professional experience related to the role.
#
#     7. Internally assess candidate suitability based on responses in three categories:
#     - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
#     - Educational: Evaluate qualifications against requirements.
#     - Professional: Assess relevant work experience.
#     Mark each area as high, medium, or low suitability without informing the candidate.
#
#     8. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.
#
#     9. You have a total of 10 questions for the entire interview.
#     10. important: If a candidate's answer is unclear, you may ask and need to ask for clarification once per question.
#     11. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
#     12. Do not provide any assessment or report at the end of the interview.
#     13. Maintain a neutral, professional tone throughout.
#     14. Do not reveal assessments or provide feedback on responses.
#     15. Transition between questions naturally without numbering or explaining their purpose.
#     """
#
#     message_history[session_id].append({"role": "system", "content": system_message})
#     initial_greeting = get_chatgpt_response("Start the interview with a greeting and introduction.", session_id)
#     audio_data = text_to_speech_openai(initial_greeting)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     interview_sessions[session_id]["started"] = True
#
#     return jsonify({"message": initial_greeting, "audio": audio_base64})
#
#
# @app.route('/send_message', methods=['POST'])
# def send_message():
#     user_message = request.form['message']
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     if interview_completed.get(session_id, False):
#         return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
#                         "interview_completed": True})
#
#     if question_count[session_id] < 10:
#         ai_response = get_chatgpt_response(user_message, session_id)
#         question_count[session_id] += 1
#     else:
#         ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.",
#                                            session_id)
#         interview_completed[session_id] = True
#         # Automatically generate report
#         report, passed = generate_report(session_id)
#         logging.debug(f"Interview completed for session {session_id}. Report generated: {report[:100]}...")
#
#     audio_data = text_to_speech_openai(ai_response)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     return jsonify({
#         "message": ai_response,
#         "audio": audio_base64,
#         "interview_completed": interview_completed.get(session_id, False)
#     })
#
#
# def generate_report(session_id):
#     logging.debug(f"Generating report for session {session_id}")
#
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     candidate = candidates[candidate_id]
#
#     report_prompt = f"""
#     You are an AI HR assistant tasked with evaluating {candidate['full_name']} (ID: {candidate_id}) based on their interview for the position of {job_title} at Amazon. Review the entire conversation above and provide a detailed assessment including:
#
#     1. An executive summary with an overall pass/fail decision and key strengths.
#     2. Detailed assessments of:
#        - Geographical compatibility
#        - Educational background
#        - Professional experience
#     3. Interview insights
#     4. Potential areas for growth
#     5. A conclusion with a final decision
#
#     Present this information in the following format:
#
#     [Amazon Logo]
#
#     CANDIDATE EVALUATION REPORT
#     ===========================
#
#     Candidate: [Full Name] (ID: [Candidate ID])
#     Position: [Job Title]
#     Interview Date: [Current Date]
#
#     EXECUTIVE SUMMARY
#     -----------------
#     OVERALL DECISION: [PASS/FAIL] [✅/❌]
#
#     🏆 Recommendation: [Your recommendation]
#     🎯 Overall Fit: [Your assessment]
#     🚀 Key Strength: [Main strength]
#
#         DETAILED ASSESSMENT
#         -------------------
#
#         📍 Geographical Compatibility
#            Status: [Your assessment]
#            • [Key points]
#
#         🎓 Educational Background
#            Status: [Your assessment]
#            • [Key points]
#
#         💼 Professional Experience
#            Status: [Your assessment]
#            • [Key points]
#
#         INTERVIEW INSIGHTS
#         ------------------
#         • [Key insights from the interview]
#
#         POTENTIAL AREAS FOR GROWTH
#         --------------------------
#         • [Areas for improvement or development]
#
#         CONCLUSION
#         ----------
#         [A paragraph summarizing the candidate's fit and potential]
#
#         FINAL DECISION: [PASS/FAIL] [✅/❌]
#         [Final recommendation]
#
#         [AI Interviewer Signature]
#         Maya
#         AI HR Interviewer
#         Amazon
#
#         Important: Make sure to base your assessment solely on the information provided in the interview conversation. If certain details are missing, make reasonable assumptions and note them in your report.
#         """
#
#     message_history[session_id].append({"role": "user", "content": report_prompt})
#
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history[session_id]
#     )
#     report = response.choices[0].message.content.strip()
#
#     # Determine if the candidate passed
#     passed = "PASS" in report.split("OVERALL DECISION:")[-1].split("\n")[0]
#
#     # Save the report to a text file
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         os.makedirs(report_folder)
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(report_folder, report_filename)
#     try:
#         with open(report_path, 'w', encoding='utf-8') as f:
#             f.write(report)
#         logging.debug(f"Report saved to {report_path}")
#
#         # Update candidate information with report filename
#         candidates[candidate_id]['report_filename'] = report_filename
#
#     except Exception as e:
#         logging.error(f"Error saving report to file: {e}")
#
#     return report, passed
#
#
# def get_candidate_status(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         with open(report_path, 'r', encoding='utf-8') as f:
#             content = f.read()
#             return "PASS" in content.split("FINAL DECISION:")[-1].split("\n")[0]
#     return False
#
#
# @app.route('/get_all_job_descriptions')
# def get_all_job_descriptions():
#     job_descriptions = []
#     for filename in os.listdir(app.config['UPLOAD_FOLDER']):
#         if filename.endswith('.txt'):
#             job_title = filename[:-4]  # Remove .txt extension
#             job_descriptions.append({"title": job_title, "file_name": filename})
#     return jsonify({"job_descriptions": job_descriptions})
#
#
# @app.route('/delete_job/<job_title>', methods=['POST'])
# def delete_job(job_title):
#     job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#
#     try:
#         if os.path.exists(job_file):
#             os.remove(job_file)
#         if os.path.exists(report_folder):
#             shutil.rmtree(report_folder)
#         # Remove candidates associated with this job
#         candidates_to_remove = [cid for cid, c in candidates.items() if c['job_title'] == job_title]
#         for cid in candidates_to_remove:
#             del candidates[cid]
#         return jsonify({"success": True})
#     except Exception as e:
#         logging.error(f"Error deleting job {job_title}: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# def get_chatgpt_response(question, session_id):
#     message_history[session_id].append({"role": "user", "content": question})
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history[session_id]
#     )
#     chat_response = response.choices[0].message.content.strip()
#     message_history[session_id].append({"role": "assistant", "content": chat_response})
#     return chat_response
#
#
# def text_to_speech_openai(text):
#     response = client.audio.speech.create(
#         model="tts-1",
#         voice="nova",
#         input=text
#     )
#     return response.content
#
#
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=8080)
#
# #
#
































































































# from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
# from openai import OpenAI
# import base64
# import os
# import logging
# import uuid
# import shutil
# from datetime import datetime
# import random
#
# app = Flask(__name__)
#
# logging.basicConfig(level=logging.DEBUG)
#
# my_key = "sk-proj-86fpKmKwBlTjtdKk5JdAT3BlbkFJ05rqWxMargDkMwMH2CRJ"
# client = OpenAI(api_key=my_key)
#
# message_history = {}
# job_description = ""
# question_count = {}
# interview_completed = {}
#
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'cvs'))
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#
# interview_sessions = {}
# candidates = {}
#
#
# @app.route('/')
# def home():
#     job_title = request.args.get('job_title')
#     if not job_title:
#         return "Invalid interview link. Please contact the HR department.", 400
#     return render_template('index.html', job_title=job_title)
#
#
# @app.route('/company')
# def company_interface():
#     return render_template('company_interface.html')
#
#
# @app.route('/upload_job_description', methods=['POST'])
# def upload_job_description():
#     job_title = request.form['job_title']
#     file = request.files['file']
#     if file:
#         filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         file.save(filename)
#         return jsonify({"message": "Job description uploaded successfully."})
#     return jsonify({"error": "No file uploaded"}), 400
#
#
# @app.route('/get_job_description/<job_title>')
# def get_job_description(job_title):
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             content = f.read()
#         return jsonify({"content": content})
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#
# @app.route('/get_candidates/<job_title>')
# def get_candidates(job_title):
#     candidates_list = []
#     for candidate in candidates.values():
#         if candidate['job_title'] == job_title:
#             passed = get_candidate_status(job_title, candidate['candidate_id'])
#             candidates_list.append({**candidate, 'passed': passed})
#     return jsonify({"candidates": candidates_list})
#
#
# @app.route('/create_interview_link/<job_title>', methods=['POST'])
# def create_interview_link(job_title):
#     interview_url = url_for('home', job_title=job_title, _external=True)
#     return jsonify({"interview_url": interview_url})
#
#
# @app.route('/download_cv/<candidate_id>')
# def download_cv(candidate_id):
#     if candidate_id in candidates:
#         cv_filename = candidates[candidate_id]['cv_filename']
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         return send_file(cv_path, as_attachment=True)
#     return "CV not found", 404
#
#
# @app.route('/download_report/<job_title>/<candidate_id>')
# def download_report(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         return send_file(report_path, as_attachment=True)
#     return "Report not found", 404
#
#
# @app.route('/view_report/<job_title>/<candidate_id>')
# def view_report(job_title, candidate_id):
#     logging.debug(f"Attempting to view report for job: {job_title}, candidate: {candidate_id}")
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     logging.debug(f"Looking for report at: {report_path}")
#
#     if os.path.exists(report_path):
#         try:
#             with open(report_path, 'r', encoding='utf-8') as f:
#                 report_content = f.read()
#             logging.debug(f"Report found and read: {report_content[:100]}...")  # Log the first 100 characters
#             return jsonify({"report": report_content})
#         except Exception as e:
#             logging.error(f"Error reading report: {str(e)}")
#             return jsonify({"error": f"Error reading report: {str(e)}"}), 500
#     else:
#         logging.error(f"Report not found at {report_path}")
#         return jsonify({"error": "Report not found"}), 404
#
#
# @app.route('/delete_candidate/<job_title>/<candidate_id>', methods=['POST'])
# def delete_candidate(job_title, candidate_id):
#     if candidate_id in candidates:
#         del candidates[candidate_id]
#         cv_filename = f"{candidate_id}_CV.pdf"
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         if os.path.exists(cv_path):
#             os.remove(cv_path)
#         report_filename = f"report_{candidate_id}.txt"
#         report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#         if os.path.exists(report_path):
#             os.remove(report_path)
#         return jsonify({"success": True})
#     return jsonify({"success": False, "error": "Candidate not found"}), 404
#
#
# @app.route('/register_candidate', methods=['POST'])
# def register_candidate():
#     try:
#         full_name = request.form['full_name']
#         email = request.form['email']
#         phone = request.form.get('phone', '')
#         job_title = request.form['job_title']
#         cv_file = request.files['cv']
#
#         # Check if the job exists
#         job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         if not os.path.exists(job_file):
#             return jsonify({"error": f"Job description for '{job_title}' does not exist"}), 400
#
#         # Generate Candidate ID
#         name_parts = full_name.split(' ')
#         if len(name_parts) < 2:
#             first_name = name_parts[0]
#             last_name = "Unknown"
#         else:
#             first_name = name_parts[0]
#             last_name = ' '.join(name_parts[1:])
#
#         id_prefix = f"{first_name[:2].upper()}-{last_name[:2].upper()}"
#         id_suffix = phone[-4:] if phone else ''.join([str(random.randint(0, 9)) for _ in range(4)])
#         timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#         candidate_id = f"{id_prefix}-{id_suffix}-{timestamp}"
#
#         # Save CV
#         cv_filename = f"{candidate_id}_CV.pdf"
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         os.makedirs(os.path.dirname(cv_path), exist_ok=True)
#         cv_file.save(cv_path)
#
#         # Store candidate information
#         candidates[candidate_id] = {
#             'full_name': full_name,
#             'email': email,
#             'phone': phone,
#             'job_title': job_title,
#             'cv_filename': cv_filename,
#             'candidate_id': candidate_id
#         }
#
#         # Create interview session
#         session_id = str(uuid.uuid4())
#         interview_sessions[session_id] = {
#             "job_title": job_title,
#             "candidate_id": candidate_id,
#             "started": False
#         }
#
#         return jsonify({"session_id": session_id, "candidate_id": candidate_id})
#     except Exception as e:
#         app.logger.error(f"Error in register_candidate: {str(e)}")
#         return jsonify({"error": f"Registration failed: {str(e)}"}), 500
#
#
# @app.route('/interview/<session_id>')
# def interview(session_id):
#     if session_id not in interview_sessions:
#         return "Invalid interview session", 404
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     return render_template('index.html', session_id=session_id, job_title=job_title, candidate_id=candidate_id)
#
#
# @app.route('/start_interview', methods=['POST'])
# def start_interview():
#     session_id = request.form.get('session_id')
#     job_title = request.form.get('job_title')
#     candidate_id = request.form.get('candidate_id')
#
#     if not session_id or not job_title or not candidate_id:
#         return jsonify({"error": "Missing session_id, job_title, or candidate_id"}), 400
#
#     if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or already started session"}), 400
#
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             job_description = f.read()
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#     question_count[session_id] = 0
#     interview_completed[session_id] = False
#     message_history[session_id] = []
#
#     candidate_name = candidates[candidate_id]['full_name']
#     system_message = f"""
#     You are Maya, an AI HR interviewer for Google. You're interviewing {candidate_name} for the position of {job_title}.
#     Carefully read and understand the following job description:
#     {job_description}
#
#     Follow these guidelines:
#     1. Always address the candidate by their name: {candidate_name}
#     2. Always mention the correct location for the job as specified in the job description. Do not assume or mention any location not explicitly stated in the job description.
#     3. Do not use time-specific greetings like "Good morning" or "Good afternoon"
#     4. Start with a formal but polite greeting, introducing yourself, the position, and the correct location from the job description
#     5. Ask if the candidate is ready to begin the interview
#     6. Conduct the interview naturally, as a real HR professional would:
#     - Ask questions one at a time, without mentioning their purpose or labeling them.
#     - Start by asking about the candidate's current location.
#     - Internally assess the location's suitability:
#       a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
#       b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
#       c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role.
#     - Inquire about educational background relevant to the position.
#     - Ask about professional experience related to the role.
#     7. Internally assess candidate suitability based on responses in three categories:
#     - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
#     - Educational: Evaluate qualifications against requirements.
#     - Professional: Assess relevant work experience.
#     Mark each area as high, medium, or low suitability without informing the candidate.
#     8. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.
#     9. You have a total of 10 questions for the entire interview.
#     10. If a candidate's answer is unclear, you may ask for clarification once per question.
#     11. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
#     12. Do not provide any assessment or report at the end of the interview.
#     13. Maintain a neutral, professional tone throughout.
#     14. Do not reveal assessments or provide feedback on responses.
#     15. Transition between questions naturally without numbering or explaining their purpose.
#
#     Remember: Accuracy in representing the job details, especially the location, is crucial. Only use information explicitly stated in the job description.
#     """
#
#     message_history[session_id].append({"role": "system", "content": system_message})
#     initial_greeting = get_chatgpt_response(f"Start the interview by greeting {candidate_name}, introducing yourself, mentioning the {job_title} position and its location as specified in the job description. Ask if they're ready to begin. Do not use time-specific greetings.", session_id)
#     audio_data = text_to_speech_openai(initial_greeting)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     interview_sessions[session_id]["started"] = True
#
#     return jsonify({"message": initial_greeting, "audio": audio_base64})
#
#
# @app.route('/send_message', methods=['POST'])
# def send_message():
#     user_message = request.form['message']
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     if interview_completed.get(session_id, False):
#         return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
#                         "interview_completed": True})
#
#     if question_count[session_id] < 10:
#         ai_response = get_chatgpt_response(user_message, session_id)
#         question_count[session_id] += 1
#     else:
#         ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.", session_id)
#         interview_completed[session_id] = True
#         # Automatically generate report
#         report, passed = generate_report(session_id)
#         logging.debug(f"Interview completed for session {session_id}. Report generated: {report[:100]}...")
#
#     audio_data = text_to_speech_openai(ai_response)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     response_data = {
#         "message": ai_response,
#         "audio": audio_base64,
#         "interview_completed": interview_completed.get(session_id, False)
#     }
#
#     if interview_completed.get(session_id, False):
#         response_data["report"] = report
#         response_data["passed"] = passed
#
#     return jsonify(response_data)
#
#
# def generate_report(session_id):
#     logging.debug(f"Generating report for session {session_id}")
#
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     candidate = candidates[candidate_id]
#
#     report_prompt = f"""
#     You are an AI HR assistant tasked with evaluating {candidate['full_name']} (ID: {candidate_id}) based on their interview for the position of {job_title} at Google. Review the entire conversation above and provide a detailed assessment including:
#
#     1. An executive summary with an overall pass/fail decision and key strengths.
#     2. Detailed assessments of:
#        - Geographical compatibility
#        - Educational background
#        - Professional experience
#     3. Interview insights
#     4. Potential areas for growth
#     5. A conclusion with a final decision
#
#     Present this information in the following format:
#
#     [Google Logo]
#
#     CANDIDATE EVALUATION REPORT
#     ===========================
#
#     Candidate: [Full Name] (ID: [Candidate ID])
#     Position: [Job Title]
#     Interview Date: [Current Date]
#
#     EXECUTIVE SUMMARY
#     -----------------
#     OVERALL DECISION: [PASS/FAIL] [✅/❌]
#
#     🏆 Recommendation: [Your recommendation]
#     🎯 Overall Fit: [Your assessment]
#     🚀 Key Strength: [Main strength]
#
#     DETAILED ASSESSMENT
#     -------------------
#
#     📍 Geographical Compatibility
#        Status: [Your assessment]
#        • [Key points]
#
#     🎓 Educational Background
#        Status: [Your assessment]
#        • [Key points]
#
#     💼 Professional Experience
#        Status: [Your assessment]
#        • [Key points]
#
#     INTERVIEW INSIGHTS
#     ------------------
#     • [Key insights from the interview]
#
#     POTENTIAL AREAS FOR GROWTH
#     --------------------------
#     • [Areas for improvement or development]
#
#     CONCLUSION
#     ----------
#     [A paragraph summarizing the candidate's fit and potential]
#
#     FINAL DECISION: [PASS/FAIL] [✅/❌]
#     [Final recommendation]
#
#     [AI Interviewer Signature]
#     Maya
#     AI HR Interviewer
#     Google
#
#     Important: Make sure to base your assessment solely on the information provided in the interview conversation. If certain details are missing, make reasonable assumptions and note them in your report.
#     """
#
#     # Create a new conversation for report generation
#     report_conversation = message_history[session_id].copy()
#     report_conversation.append({"role": "user", "content": report_prompt})
#
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=report_conversation
#     )
#     report = response.choices[0].message.content.strip()
#
#     # Determine if the candidate passed
#     passed = "PASS" in report.split("OVERALL DECISION:")[-1].split("\n")[0]
#
#     # Save the report to a text file
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         os.makedirs(report_folder)
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(report_folder, report_filename)
#     try:
#         with open(report_path, 'w', encoding='utf-8') as f:
#             f.write(report)
#         logging.debug(f"Report saved to {report_path}")
#
#         # Update candidate information with report filename
#         candidates[candidate_id]['report_filename'] = report_filename
#
#     except Exception as e:
#         logging.error(f"Error saving report to file: {e}")
#
#     return report, passed
#
#
# def get_candidate_status(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         with open(report_path, 'r', encoding='utf-8') as f:
#             content = f.read()
#             return "PASS" in content.split("FINAL DECISION:")[-1].split("\n")[0]
#     return False
#
#
# @app.route('/get_all_job_descriptions')
# def get_all_job_descriptions():
#     job_descriptions = []
#     for filename in os.listdir(app.config['UPLOAD_FOLDER']):
#         if filename.endswith('.txt'):
#             job_title = filename[:-4]  # Remove .txt extension
#             job_descriptions.append({"title": job_title, "file_name": filename})
#     return jsonify({"job_descriptions": job_descriptions})
#
#
# @app.route('/delete_job/<job_title>', methods=['POST'])
# def delete_job(job_title):
#     job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#
#     try:
#         if os.path.exists(job_file):
#             os.remove(job_file)
#         if os.path.exists(report_folder):
#             shutil.rmtree(report_folder)
#         # Remove candidates associated with this job
#         candidates_to_remove = [cid for cid, c in candidates.items() if c['job_title'] == job_title]
#         for cid in candidates_to_remove:
#             del candidates[cid]
#         return jsonify({"success": True})
#     except Exception as e:
#         logging.error(f"Error deleting job {job_title}: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# def get_chatgpt_response(question, session_id):
#     message_history[session_id].append({"role": "user", "content": question})
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history[session_id]
#     )
#     chat_response = response.choices[0].message.content.strip()
#     message_history[session_id].append({"role": "assistant", "content": chat_response})
#     return chat_response
#
#
# def text_to_speech_openai(text):
#     response = client.audio.speech.create(
#         model="tts-1",
#         voice="nova",
#         input=text
#     )
#     return response.content
#
#
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=8080)


































































































# from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
# from openai import OpenAI
# import base64
# import os
# import logging
# import uuid
#
# app = Flask(__name__)
#
# logging.basicConfig(level=logging.DEBUG)
#
# my_key = "sk-proj-86fpKmKwBlTjtdKk5JdAT3BlbkFJ05rqWxMargDkMwMH2CRJ"
# client = OpenAI(api_key=my_key)
#
# message_history = []
# job_description = ""
# question_count = 0
# interview_completed = False
#
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#
# interview_sessions = {}
#
#
# @app.route('/')
# def home():
#     return render_template('index.html')
#
#
# @app.route('/company')
# def company_interface():
#     return render_template('company_interface.html')
#
#
# @app.route('/upload_job_description', methods=['POST'])
# def upload_job_description():
#     job_title = request.form['job_title']
#     file = request.files['file']
#     if file:
#         filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         file.save(filename)
#         return jsonify({"message": "Job description uploaded successfully."})
#     return jsonify({"error": "No file uploaded"}), 400
#
#
# @app.route('/get_job_description/<job_title>')
# def get_job_description(job_title):
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             content = f.read()
#         return jsonify({"content": content})
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#
# @app.route('/get_reports/<job_title>')
# def get_reports(job_title):
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         return jsonify({"reports": []})
#     reports = [f for f in os.listdir(report_folder) if f.endswith('.txt')]
#     return jsonify({"reports": reports})
#
#
# @app.route('/download_report/<job_title>/<report_name>')
# def download_report(job_title, report_name):
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_name)
#     return send_file(report_path, as_attachment=True)
#
#
# @app.route('/start_new_interview/<job_title>', methods=['POST'])
# def start_new_interview(job_title):
#     session_id = str(uuid.uuid4())
#     interview_sessions[session_id] = {"job_title": job_title, "started": False}
#     interview_url = url_for('interview', session_id=session_id, _external=True)
#     return jsonify({"interview_url": interview_url, "session_id": session_id})
#
#
# @app.route('/interview/<session_id>')
# def interview(session_id):
#     if session_id not in interview_sessions:
#         return "Invalid interview session", 404
#     job_title = interview_sessions[session_id]["job_title"]
#     return render_template('index.html', session_id=session_id, job_title=job_title)
#
#
# @app.route('/start_interview', methods=['POST'])
# def start_interview():
#     global message_history, question_count, interview_completed
#     session_id = request.form.get('session_id')
#     job_title = request.form.get('job_title')
#
#     if not session_id or not job_title:
#         return jsonify({"error": "Missing session_id or job_title"}), 400
#
#     if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or already started session"}), 400
#
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             job_description = f.read()
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#     question_count = 0
#     interview_completed = False
#     system_message = f"""
#     You are an AI HR interviewer. Your task is to conduct an interview based on the following job description:
#     {job_description}
#
#     Follow these guidelines:
#     1. Your name is "Maya"
#     2. Start with a formal but polite greeting. Introduce yourself as an AI HR interviewer for the company mentioned in the job description.txt file learn this file well.
#     3. Don't make mistakes in the company name or location of the position! Do double check with the job description.txt file.
#     4. Inform the candidate about the position they're interviewing for.
#     5. Ask if they're ready to begin the interview.
#     6. Conduct the interview naturally, as a real HR professional would:
#     - Ask questions one at a time, without mentioning their purpose or labeling them.
#     - Start by asking about the candidate's current location.
#     - Internally assess the location's suitability:
#     note : when you ask and check candidate that you cant write it down relatively far and speak relative rather than in exact time and also Do not offer or ask about relocation, just listen to their opinion on how they will deal with it.
#       a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
#       b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
#       c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role.
#     - Inquire about educational background relevant to the position.
#     - Ask about professional experience related to the role.
#
#     7. Internally assess candidate suitability based on responses in three categories:
#     - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
#     - Educational: Evaluate qualifications against requirements.
#     - Professional: Assess relevant work experience.
#     Mark each area as high, medium, or low suitability without informing the candidate.
#
#     8. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.
#
#     9. You have a total of 10 questions for the entire interview.
#     10. important: If a candidate's answer is unclear, you may ask and need to ask for clarification once per question.
#     11. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
#     12. Do not provide any assessment or report at the end of the interview.
#     13. Maintain a neutral, professional tone throughout.
#     14. Do not reveal assessments or provide feedback on responses.
#     15. Transition between questions naturally without numbering or explaining their purpose.
#     """
#
#     message_history = [{"role": "system", "content": system_message}]
#     initial_greeting = get_chatgpt_response("Start the interview with a greeting and introduction.")
#     audio_data = text_to_speech_openai(initial_greeting)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     interview_sessions[session_id]["started"] = True
#
#     return jsonify({"message": initial_greeting, "audio": audio_base64})
#
#
# @app.route('/send_message', methods=['POST'])
# def send_message():
#     global question_count, interview_completed
#     user_message = request.form['message']
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     if interview_completed:
#         return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
#                         "interview_completed": True})
#
#     if question_count < 10:
#         ai_response = get_chatgpt_response(user_message)
#         question_count += 1
#     else:
#         ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.")
#         interview_completed = True
#
#     audio_data = text_to_speech_openai(ai_response)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#     return jsonify({"message": ai_response, "audio": audio_base64, "interview_completed": interview_completed})
#
#
# @app.route('/generate_report', methods=['POST'])
# def generate_report():
#     logging.debug("Generate report function called")
#     global message_history
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     job_title = interview_sessions[session_id]["job_title"]
#
#     report_prompt = f"""
#     You are an AI HR assistant tasked with evaluating a candidate based on their interview for the position of {job_title}. Review the entire conversation above and provide a detailed assessment including:
#
#     1. Geographical compatibility (high/medium/low):
#        - Explain the rating based on the candidate's location and willingness to commute.
#
#     2. Educational background (high/medium/low):
#        - Evaluate the relevance and quality of their education for the position.
#
#     3. Professional experience (high/medium/low):
#        - Assess their work history and skills relevant to the job.
#
#     4. Overall recommendation:
#        - Should the candidate proceed to the next stage? (Yes/No)
#        - Remember, only the top 20% most impressive candidates should proceed.
#
#     5. Brief explanation for the recommendation (2-3 sentences).
#
#     Present this information in a clear, concise format. Base your assessment solely on the information provided in the interview conversation.
#
#     Important: Do not apologize or state that you can't provide an assessment. Always provide a detailed report based on the available information. If certain details are missing, make reasonable assumptions and note them in your report.
#     """
#
#     message_history.append({"role": "user", "content": report_prompt})
#
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history
#     )
#     report = response.choices[0].message.content.strip()
#
#     # Save the report to a text file
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         os.makedirs(report_folder)
#     report_filename = f"report_{session_id}.txt"
#     report_path = os.path.join(report_folder, report_filename)
#     try:
#         with open(report_path, 'w', encoding='utf-8') as f:
#             f.write(report)
#         logging.debug(f"Report saved to {report_path}")
#     except Exception as e:
#         logging.error(f"Error saving report to file: {e}")
#
#     # Generate audio for the report
#     audio_data = text_to_speech_openai(report)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     logging.debug(f"Report generated: {report}")
#     return jsonify({"report": report, "audio": audio_base64, "report_filename": report_filename})
#
#
# @app.route('/get_all_job_descriptions')
# def get_all_job_descriptions():
#     job_descriptions = []
#     for filename in os.listdir(app.config['UPLOAD_FOLDER']):
#         if filename.endswith('.txt'):
#             job_title = filename[:-4]  # Remove .txt extension
#             job_descriptions.append({"title": job_title, "file_name": filename})
#     return jsonify({"job_descriptions": job_descriptions})
#
#
# def get_chatgpt_response(question):
#     message_history.append({"role": "user", "content": question})
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history
#     )
#     chat_response = response.choices[0].message.content.strip()
#     message_history.append({"role": "assistant", "content": chat_response})
#     return chat_response
#
#
# def text_to_speech_openai(text):
#     response = client.audio.speech.create(
#         model="tts-1",
#         voice="nova",
#         input=text
#     )
#     return response.content
#
#
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=8080)
#
#
# from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
# from openai import OpenAI
# import base64
# import os
# import logging
# import uuid
# import shutil
#
# app = Flask(__name__)
#
# logging.basicConfig(level=logging.DEBUG)
#
# my_key = "sk-proj-86fpKmKwBlTjtdKk5JdAT3BlbkFJ05rqWxMargDkMwMH2CRJ"
# client = OpenAI(api_key=my_key)
#
# message_history = []
# job_description = ""
# question_count = 0
# interview_completed = False
#
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#
# interview_sessions = {}
#
#
# @app.route('/')
# def home():
#     return render_template('index.html')
#
#
# @app.route('/company')
# def company_interface():
#     return render_template('company_interface.html')
#
#
# @app.route('/upload_job_description', methods=['POST'])
# def upload_job_description():
#     job_title = request.form['job_title']
#     file = request.files['file']
#     if file:
#         filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         file.save(filename)
#         return jsonify({"message": "Job description uploaded successfully."})
#     return jsonify({"error": "No file uploaded"}), 400
#
#
# @app.route('/get_job_description/<job_title>')
# def get_job_description(job_title):
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             content = f.read()
#         return jsonify({"content": content})
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#
# @app.route('/get_reports/<job_title>')
# def get_reports(job_title):
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         return jsonify({"reports": []})
#     reports = [f for f in os.listdir(report_folder) if f.endswith('.txt')]
#     return jsonify({"reports": reports})
#
#
# @app.route('/download_report/<job_title>/<report_name>')
# def download_report(job_title, report_name):
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_name)
#     return send_file(report_path, as_attachment=True)
#
#
# @app.route('/start_new_interview/<job_title>', methods=['POST'])
# def start_new_interview(job_title):
#     session_id = str(uuid.uuid4())
#     interview_sessions[session_id] = {"job_title": job_title, "started": False}
#     interview_url = url_for('interview', session_id=session_id, _external=True)
#     return jsonify({"interview_url": interview_url, "session_id": session_id})
#
#
# @app.route('/interview/<session_id>')
# def interview(session_id):
#     if session_id not in interview_sessions:
#         return "Invalid interview session", 404
#     job_title = interview_sessions[session_id]["job_title"]
#     return render_template('index.html', session_id=session_id, job_title=job_title)
#
#
# @app.route('/start_interview', methods=['POST'])
# def start_interview():
#     global message_history, question_count, interview_completed
#     session_id = request.form.get('session_id')
#     job_title = request.form.get('job_title')
#
#     if not session_id or not job_title:
#         return jsonify({"error": "Missing session_id or job_title"}), 400
#
#     if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or already started session"}), 400
#
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             job_description = f.read()
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#     question_count = 0
#     interview_completed = False
#     system_message = f"""
#     You are an AI HR interviewer. Your task is to conduct an interview based on the following job description:
#     {job_description}
#
#     Follow these guidelines:
#     1. Your name is "Maya"
#     2. Start with a formal but polite greeting. Introduce yourself as an AI HR interviewer for the company mentioned in the job description.txt file learn this file well.
#     3. Don't make mistakes in the company name or location of the position! Do double check with the job description.txt file.
#     4. Inform the candidate about the position they're interviewing for.
#     5. Ask if they're ready to begin the interview.
#     6. Conduct the interview naturally, as a real HR professional would:
#     - Ask questions one at a time, without mentioning their purpose or labeling them.
#     - Start by asking about the candidate's current location.
#     - Internally assess the location's suitability:
#     note : when you ask and check candidate that you cant write it down relatively far and speak relative rather than in exact time and also Do not offer or ask about relocation, just listen to their opinion on how they will deal with it.
#       a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
#       b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
#       c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role.
#     - Inquire about educational background relevant to the position.
#     - Ask about professional experience related to the role.
#
#     7. Internally assess candidate suitability based on responses in three categories:
#     - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
#     - Educational: Evaluate qualifications against requirements.
#     - Professional: Assess relevant work experience.
#     Mark each area as high, medium, or low suitability without informing the candidate.
#
#     8. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.
#
#     9. You have a total of 10 questions for the entire interview.
#     10. important: If a candidate's answer is unclear, you may ask and need to ask for clarification once per question.
#     11. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
#     12. Do not provide any assessment or report at the end of the interview.
#     13. Maintain a neutral, professional tone throughout.
#     14. Do not reveal assessments or provide feedback on responses.
#     15. Transition between questions naturally without numbering or explaining their purpose.
#     """
#
#     message_history = [{"role": "system", "content": system_message}]
#     initial_greeting = get_chatgpt_response("Start the interview with a greeting and introduction.")
#     audio_data = text_to_speech_openai(initial_greeting)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     interview_sessions[session_id]["started"] = True
#
#     return jsonify({"message": initial_greeting, "audio": audio_base64})
#
#
# @app.route('/send_message', methods=['POST'])
# def send_message():
#     global question_count, interview_completed
#     user_message = request.form['message']
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     if interview_completed:
#         return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
#                         "interview_completed": True})
#
#     if question_count < 10:
#         ai_response = get_chatgpt_response(user_message)
#         question_count += 1
#     else:
#         ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.")
#         interview_completed = True
#         # Automatically generate report
#         generate_report(session_id)
#
#     audio_data = text_to_speech_openai(ai_response)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#     return jsonify({"message": ai_response, "audio": audio_base64, "interview_completed": interview_completed})
#
#
# def generate_report(session_id):
#     logging.debug("Generate report function called")
#     global message_history
#
#     job_title = interview_sessions[session_id]["job_title"]
#
#     report_prompt = f"""
#     You are an AI HR assistant tasked with evaluating a candidate based on their interview for the position of {job_title}. Review the entire conversation above and provide a detailed assessment including:
#
#     1. Geographical compatibility (high/medium/low):
#        - Explain the rating based on the candidate's location and willingness to commute.
#
#     2. Educational background (high/medium/low):
#        - Evaluate the relevance and quality of their education for the position.
#
#     3. Professional experience (high/medium/low):
#        - Assess their work history and skills relevant to the job.
#
#     4. Overall recommendation:
#        - Should the candidate proceed to the next stage? (Yes/No)
#        - Remember, only the top 20% most impressive candidates should proceed.
#
#     5. Brief explanation for the recommendation (2-3 sentences).
#
#     Present this information in a clear, concise format. Base your assessment solely on the information provided in the interview conversation.
#
#     Important: Do not apologize or state that you can't provide an assessment. Always provide a detailed report based on the available information. If certain details are missing, make reasonable assumptions and note them in your report.
#     """
#
#     message_history.append({"role": "user", "content": report_prompt})
#
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history
#     )
#     report = response.choices[0].message.content.strip()
#
#     # Save the report to a text file
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         os.makedirs(report_folder)
#     report_filename = f"report_{session_id}.txt"
#     report_path = os.path.join(report_folder, report_filename)
#     try:
#         with open(report_path, 'w', encoding='utf-8') as f:
#             f.write(report)
#         logging.debug(f"Report saved to {report_path}")
#     except Exception as e:
#         logging.error(f"Error saving report to file: {e}")
#
#
# @app.route('/get_all_job_descriptions')
# def get_all_job_descriptions():
#     job_descriptions = []
#     for filename in os.listdir(app.config['UPLOAD_FOLDER']):
#         if filename.endswith('.txt'):
#             job_title = filename[:-4]  # Remove .txt extension
#             job_descriptions.append({"title": job_title, "file_name": filename})
#     return jsonify({"job_descriptions": job_descriptions})
#
#
# @app.route('/delete_job/<job_title>', methods=['POST'])
# def delete_job(job_title):
#     job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#
#     try:
#         if os.path.exists(job_file):
#             os.remove(job_file)
#         if os.path.exists(report_folder):
#             shutil.rmtree(report_folder)
#         return jsonify({"success": True})
#     except Exception as e:
#         logging.error(f"Error deleting job {job_title}: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# @app.route('/delete_report/<job_title>/<report_name>', methods=['POST'])
# def delete_report(job_title, report_name):
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_name)
#     try:
#         if os.path.exists(report_path):
#             os.remove(report_path)
#         return jsonify({"success": True})
#     except Exception as e:
#         logging.error(f"Error deleting report {report_name} for job {job_title}: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# def get_chatgpt_response(question):
#     message_history.append({"role": "user", "content": question})
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history
#     )
#     chat_response = response.choices[0].message.content.strip()
#     message_history.append({"role": "assistant", "content": chat_response})
#     return chat_response
#
#
# def text_to_speech_openai(text):
#     response = client.audio.speech.create(
#         model="tts-1",
#         voice="nova",
#         input=text
#     )
#     return response.content
#
#
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=8080)















#
#
# from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
# from openai import OpenAI
# import base64
# import os
# import logging
# import uuid
# import shutil
# from datetime import datetime
# import random
#
# app = Flask(__name__)
#
# logging.basicConfig(level=logging.DEBUG)
#
# my_key = "sk-proj-86fpKmKwBlTjtdKk5JdAT3BlbkFJ05rqWxMargDkMwMH2CRJ"
# client = OpenAI(api_key=my_key)
#
# message_history = {}
# job_description = ""
# question_count = {}
# interview_completed = {}
#
# UPLOAD_FOLDER = 'uploads'
# if not os.path.exists(UPLOAD_FOLDER):
#     os.makedirs(UPLOAD_FOLDER)
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'cvs'))
#     os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'))
# app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
#
# interview_sessions = {}
# candidates = {}
#
#
# @app.route('/')
# def home():
#     job_title = request.args.get('job_title')
#     if not job_title:
#         return "Invalid interview link. Please contact the HR department.", 400
#     return render_template('index.html', job_title=job_title)
#
#
# @app.route('/company')
# def company_interface():
#     return render_template('company_interface.html')
#
#
# @app.route('/upload_job_description', methods=['POST'])
# def upload_job_description():
#     job_title = request.form['job_title']
#     file = request.files['file']
#     if file:
#         filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         file.save(filename)
#         return jsonify({"message": "Job description uploaded successfully."})
#     return jsonify({"error": "No file uploaded"}), 400
#
#
# @app.route('/get_job_description/<job_title>')
# def get_job_description(job_title):
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             content = f.read()
#         return jsonify({"content": content})
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#
# @app.route('/get_candidates/<job_title>')
# def get_candidates(job_title):
#     candidates_list = [
#         {**candidate, 'passed': get_candidate_status(job_title, candidate['candidate_id'])}
#         for candidate in candidates.values()
#         if candidate['job_title'] == job_title
#     ]
#     return jsonify({"candidates": candidates_list})
#
#
# @app.route('/create_interview_link/<job_title>', methods=['POST'])
# def create_interview_link(job_title):
#     interview_url = url_for('home', job_title=job_title, _external=True)
#     return jsonify({"interview_url": interview_url})
#
#
# @app.route('/download_cv/<candidate_id>')
# def download_cv(candidate_id):
#     if candidate_id in candidates:
#         cv_filename = candidates[candidate_id]['cv_filename']
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         return send_file(cv_path, as_attachment=True)
#     return "CV not found", 404
#
#
# @app.route('/download_report/<job_title>/<candidate_id>')
# def download_report(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         return send_file(report_path, as_attachment=True)
#     return "Report not found", 404
#
#
# @app.route('/view_report/<job_title>/<candidate_id>')
# def view_report(job_title, candidate_id):
#     logging.debug(f"Attempting to view report for job: {job_title}, candidate: {candidate_id}")
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     logging.debug(f"Looking for report at: {report_path}")
#     if os.path.exists(report_path):
#         with open(report_path, 'r', encoding='utf-8') as f:
#             report_content = f.read()
#         logging.debug(f"Report found and read: {report_content[:100]}...")  # Log the first 100 characters
#         return jsonify({"report": report_content})
#     logging.error(f"Report not found at {report_path}")
#     return jsonify({"error": "Report not found"}), 404
#
#
# @app.route('/delete_candidate/<job_title>/<candidate_id>', methods=['POST'])
# def delete_candidate(job_title, candidate_id):
#     try:
#         if candidate_id in candidates:
#             # Remove candidate from the candidates dictionary
#             del candidates[candidate_id]
#
#             # Remove CV file
#             cv_filename = f"{candidate_id}_CV.pdf"
#             cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#             if os.path.exists(cv_path):
#                 os.remove(cv_path)
#
#             # Remove report file
#             report_filename = f"report_{candidate_id}.txt"
#             report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#             if os.path.exists(report_path):
#                 os.remove(report_path)
#
#             logging.info(f"Successfully deleted candidate {candidate_id} for job {job_title}")
#             return jsonify({"success": True})
#         else:
#             logging.warning(f"Candidate {candidate_id} not found for deletion")
#             return jsonify({"success": False, "error": "Candidate not found"}), 404
#     except Exception as e:
#         logging.error(f"Error deleting candidate {candidate_id} for job {job_title}: {str(e)}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# @app.route('/register_candidate', methods=['POST'])
# def register_candidate():
#     try:
#         full_name = request.form['full_name']
#         email = request.form['email']
#         phone = request.form.get('phone', '')
#         job_title = request.form['job_title']
#         cv_file = request.files['cv']
#
#         # Check if the job exists
#         job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#         if not os.path.exists(job_file):
#             return jsonify({"error": f"Job description for '{job_title}' does not exist"}), 400
#
#         # Generate Candidate ID
#         name_parts = full_name.split(' ')
#         if len(name_parts) < 2:
#             first_name = name_parts[0]
#             last_name = "Unknown"
#         else:
#             first_name = name_parts[0]
#             last_name = ' '.join(name_parts[1:])
#
#         id_prefix = f"{first_name[:2].upper()}-{last_name[:2].upper()}"
#         id_suffix = phone[-4:] if phone else ''.join([str(random.randint(0, 9)) for _ in range(4)])
#         timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
#         candidate_id = f"{id_prefix}-{id_suffix}-{timestamp}"
#
#         # Save CV
#         cv_filename = f"{candidate_id}_CV.pdf"
#         cv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'cvs', cv_filename)
#         os.makedirs(os.path.dirname(cv_path), exist_ok=True)
#         cv_file.save(cv_path)
#
#         # Store candidate information
#         candidates[candidate_id] = {
#             'full_name': full_name,
#             'email': email,
#             'phone': phone,
#             'job_title': job_title,
#             'cv_filename': cv_filename,
#             'candidate_id': candidate_id
#         }
#
#         # Create interview session
#         session_id = str(uuid.uuid4())
#         interview_sessions[session_id] = {
#             "job_title": job_title,
#             "candidate_id": candidate_id,
#             "started": False
#         }
#
#         return jsonify({"session_id": session_id, "candidate_id": candidate_id})
#     except Exception as e:
#         app.logger.error(f"Error in register_candidate: {str(e)}")
#         return jsonify({"error": f"Registration failed: {str(e)}"}), 500
#
#
# @app.route('/interview/<session_id>')
# def interview(session_id):
#     if session_id not in interview_sessions:
#         return "Invalid interview session", 404
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     return render_template('index.html', session_id=session_id, job_title=job_title, candidate_id=candidate_id)
#
#
# @app.route('/start_interview', methods=['POST'])
# def start_interview():
#     session_id = request.form.get('session_id')
#     job_title = request.form.get('job_title')
#     candidate_id = request.form.get('candidate_id')
#
#     if not session_id or not job_title or not candidate_id:
#         return jsonify({"error": "Missing session_id, job_title, or candidate_id"}), 400
#
#     if session_id not in interview_sessions or interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or already started session"}), 400
#
#     filename = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     try:
#         with open(filename, 'r') as f:
#             job_description = f.read()
#     except FileNotFoundError:
#         return jsonify({"error": "Job description not found"}), 404
#
#     question_count[session_id] = 0
#     interview_completed[session_id] = False
#     message_history[session_id] = []
#
#     candidate_name = candidates[candidate_id]['full_name']
#     system_message = f"""
#     You are an AI HR interviewer. Your task is to conduct an interview for {candidate_name} based on the following job description:
#     {job_description}
#
#     Follow these guidelines:
#     1. Your name is "Maya"
#     2. Start with a formal but polite greeting. Introduce yourself as an AI HR interviewer for the company mentioned in the job description.txt file learn this file well.
#     IMPORTANT: Always double-check the job location in the job description above. Do not assume or mention any location that is not explicitly stated in the job description.
#     3. Don't make mistakes in the company name or location of the position! Do double check with the job description.txt file.
#     4. Inform the candidate about the position they're interviewing for.
#     5. Ask if they're ready to begin the interview.
#     6. Conduct the interview naturally, as a real HR professional would:
#     - Ask questions one at a time, without mentioning their purpose or labeling them.
#     - Start by asking about the candidate's current location.
#     - Internally assess the location's suitability:
#     note : when you ask and check candidate that you cant write it down relatively far and speak relative rather than in exact time and also Do not offer or ask about relocation, just listen to their opinion on how they will deal with it.
#       a) If the location is within a reasonable commuting distance (e.g., same city or neighboring cities), proceed to the next question without comment.
#       b) If the location is moderately far (e.g., 1-2 hours away), ask a follow-up question about how they would manage the commute.
#       c) If the location is very far (e.g., different region or country), ask how they envision handling the distance for this role.
#     - Inquire about educational background relevant to the position.
#     - Ask about professional experience related to the role.
#
#     7. Internally assess candidate suitability based on responses in three categories:
#     - Geographical compatibility: Mark as high if within reasonable distance, medium if moderately far, low if very far.
#     - Educational: Evaluate qualifications against requirements.
#     - Professional: Assess relevant work experience.
#     Mark each area as high, medium, or low suitability without informing the candidate.
#
#     8. For any areas of concern or medium suitability, ask relevant follow-up questions naturally within the conversation flow before moving to the next topic.
#
#     9. You have a total of 10 questions for the entire interview.
#     10. important: If a candidate's answer is unclear, you may ask and need to ask for clarification once per question.
#     11. After 10 questions, conclude the interview by thanking the candidate for their participation and informing them that the interview is over. Let them know that you wish them success and will be in touch later to update them regarding the continuation of the process.
#     12. Do not provide any assessment or report at the end of the interview.
#     13. Maintain a neutral, professional tone throughout.
#     14. Do not reveal assessments or provide feedback on responses.
#     15. Transition between questions naturally without numbering or explaining their purpose.
#     """
#
#     message_history[session_id].append({"role": "system", "content": system_message})
#     initial_greeting = get_chatgpt_response("Start the interview with a greeting and introduction.", session_id)
#     audio_data = text_to_speech_openai(initial_greeting)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#
#     interview_sessions[session_id]["started"] = True
#
#     return jsonify({"message": initial_greeting, "audio": audio_base64})
#
#
# @app.route('/send_message', methods=['POST'])
# def send_message():
#     user_message = request.form['message']
#     session_id = request.form['session_id']
#
#     if session_id not in interview_sessions or not interview_sessions[session_id]["started"]:
#         return jsonify({"error": "Invalid or not started session"}), 400
#
#     if interview_completed.get(session_id, False):
#         return jsonify({"message": "The interview has concluded. Thank you for your participation.", "audio": None,
#                         "interview_completed": True})
#
#     if question_count[session_id] < 10:
#         ai_response = get_chatgpt_response(user_message, session_id)
#         question_count[session_id] += 1
#     else:
#         ai_response = get_chatgpt_response("Conclude the interview without providing any assessment or report.",
#                                            session_id)
#         interview_completed[session_id] = True
#         # Automatically generate report
#         generate_report(session_id)
#
#     audio_data = text_to_speech_openai(ai_response)
#     audio_base64 = base64.b64encode(audio_data).decode('utf-8') if audio_data else None
#     return jsonify({"message": ai_response, "audio": audio_base64,
#                     "interview_completed": interview_completed.get(session_id, False)})
#
#
# def generate_report(session_id):
#     logging.debug(f"Generating report for session {session_id}")
#
#     job_title = interview_sessions[session_id]["job_title"]
#     candidate_id = interview_sessions[session_id]["candidate_id"]
#     candidate = candidates[candidate_id]
#
#     # Get the current date
#     current_date = datetime.now().strftime("%d/%m/%Y")
#
#     report_prompt = f"""
#     You are an AI HR assistant tasked with evaluating {candidate['full_name']} (ID: {candidate_id}) based on their interview for the position of {job_title} at Amazon. Review the entire conversation above and provide a detailed assessment including:
#
#     1. An executive summary with an overall pass/fail decision and key strengths.
#     2. Detailed assessments of:
#        - Geographical compatibility
#        - Educational background
#        - Professional experience
#     3. Interview insights
#     4. Potential areas for growth
#     5. A conclusion with a final decision
#
#     Present this information in the following format:
#
#     [Amazon Logo]
#
#     CANDIDATE EVALUATION REPORT
#     ===========================
#
#     Candidate: [Full Name] (ID: [Candidate ID])
#     Position: [Job Title]
#     Interview Date: {current_date}
#
#     EXECUTIVE SUMMARY
#     -----------------
#     OVERALL DECISION: [PASS/FAIL] [✅/❌]
#
#     🏆 Recommendation: [Your recommendation]
#     🎯 Overall Fit: [Your assessment]
#     🚀 Key Strength: [Main strength]
#
#         DETAILED ASSESSMENT
#         -------------------
#
#         📍 Geographical Compatibility
#            Status: [Your assessment]
#            • [Key points]
#
#         🎓 Educational Background
#            Status: [Your assessment]
#            • [Key points]
#
#         💼 Professional Experience
#            Status: [Your assessment]
#            • [Key points]
#
#         INTERVIEW INSIGHTS
#         ------------------
#         • [Key insights from the interview]
#
#         POTENTIAL AREAS FOR GROWTH
#         --------------------------
#         • [Areas for improvement or development]
#
#         CONCLUSION
#         ----------
#         [A paragraph summarizing the candidate's fit and potential]
#
#         FINAL DECISION: [PASS/FAIL] [✅/❌]
#         [Final recommendation]
#
#         [AI Interviewer Signature]
#         Maya
#         AI HR Interviewer
#         Amazon
#
#         Important: Make sure to base your assessment solely on the information provided in the interview conversation. If certain details are missing, make reasonable assumptions and note them in your report. Use the provided interview date of {current_date} in your report.
#     """
#
#     message_history[session_id].append({"role": "user", "content": report_prompt})
#
#     response = client.chat.completions.create(
#         model="gpt-4",
#         messages=message_history[session_id]
#     )
#     report = response.choices[0].message.content.strip()
#
#     # Determine if the candidate passed
#     passed = "PASS" in report.split("OVERALL DECISION:")[-1].split("\n")[0]
#
#     # Save the report to a text file
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#     if not os.path.exists(report_folder):
#         os.makedirs(report_folder)
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(report_folder, report_filename)
#     try:
#         with open(report_path, 'w', encoding='utf-8') as f:
#             f.write(report)
#         logging.debug(f"Report saved to {report_path}")
#
#         # Update candidate information with report filename
#         candidates[candidate_id]['report_filename'] = report_filename
#
#     except Exception as e:
#         logging.error(f"Error saving report to file: {e}")
#
#     return report, passed
#
#
# def get_candidate_status(job_title, candidate_id):
#     report_filename = f"report_{candidate_id}.txt"
#     report_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title, report_filename)
#     if os.path.exists(report_path):
#         with open(report_path, 'r', encoding='utf-8') as f:
#             content = f.read()
#             return "PASS" in content.split("FINAL DECISION:")[-1].split("\n")[0]
#     return False
#
#
# @app.route('/get_all_job_descriptions')
# def get_all_job_descriptions():
#     job_descriptions = []
#     for filename in os.listdir(app.config['UPLOAD_FOLDER']):
#         if filename.endswith('.txt'):
#             job_title = filename[:-4]  # Remove .txt extension
#             job_descriptions.append({"title": job_title, "file_name": filename})
#     return jsonify({"job_descriptions": job_descriptions})
#
#
# @app.route('/delete_job/<job_title>', methods=['POST'])
# def delete_job(job_title):
#     job_file = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_title}.txt")
#     report_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'reports', job_title)
#
#     try:
#         if os.path.exists(job_file):
#             os.remove(job_file)
#         if os.path.exists(report_folder):
#             shutil.rmtree(report_folder)
#         # Remove candidates associated with this job
#         candidates_to_remove = [cid for cid, c in candidates.items() if c['job_title'] == job_title]
#         for cid in candidates_to_remove:
#             del candidates[cid]
#         return jsonify({"success": True})
#     except Exception as e:
#         logging.error(f"Error deleting job {job_title}: {e}")
#         return jsonify({"success": False, "error": str(e)}), 500
#
#
# def get_chatgpt_response(question, session_id):
#     message_history[session_id].append({"role": "user", "content": question})
#     response = client.chat.completions.create(
#         model="gpt-4-turbo",
#         messages=message_history[session_id]
#     )
#     chat_response = response.choices[0].message.content.strip()
#     message_history[session_id].append({"role": "assistant", "content": chat_response})
#     return chat_response
#
#
# def text_to_speech_openai(text):
#     response = client.audio.speech.create(
#         model="tts-1",
#         voice="nova",
#         input=text
#     )
#     return response.content
#
#
# if __name__ == '__main__':
#     app.run(debug=True, host='0.0.0.0', port=8080)
#
