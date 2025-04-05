from fastapi import FastAPI, Request, Form, HTTPException, Query, Body, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import fitz  
import json
from pathlib import Path
import uuid
import asyncio
import logging
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Validate required environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
SECRET_KEY = os.getenv("SECRET_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is missing from .env file")
if not ADMIN_CHAT_ID:
    raise ValueError("ADMIN_CHAT_ID is missing from .env file")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is missing from .env file")

# Convert ADMIN_CHAT_ID to int for comparison
ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID)

app = FastAPI(
    title="Exam Management System",
    description="A system for managing student exams with Telegram integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Create necessary directories
Path("static").mkdir(exist_ok=True)
Path("templates").mkdir(exist_ok=True)
Path("uploads").mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage (replace with database in production)
pending_students = {}
approved_students = {}
rejected_students = set()  # Track rejected students
current_exam = None
correct_answers = []  # Store correct answers for the current exam
student_results = {}  # Store student exam results

# Global Telegram bot application
telegram_app = None

# Add this with other global variables
verified_admins = set()  # Store verified admin user IDs
student_attempts = {}  # Track student exam attempts

# Pydantic models for API documentation
class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message describing what went wrong")

class StudentRequest(BaseModel):
    student_id: str = Field(..., description="The student's ID", example="12345")
    name: str = Field(..., description="The student's first name", example="John")
    surname: str = Field(..., description="The student's last name", example="Doe")

    class Config:
        json_schema_extra = {
            "example": {
                "student_id": "12345",
                "name": "John",
                "surname": "Doe"
            }
        }

class ExamSubmission(BaseModel):
    student_id: str = Field(..., description="The student's ID", example="12345")
    answers: Dict[str, str] = Field(..., description="The student's answers to the exam questions")

    class Config:
        json_schema_extra = {
            "example": {
                "student_id": "12345",
                "answers": {
                    "1": "a",
                    "2": "b",
                    "3": "c"
                }
            }
        }

class ExamResponse(BaseModel):
    message: str = Field(..., description="A message indicating the status of the exam")
    student_id: str = Field(..., description="The student's ID")
    exam_available: bool = Field(..., description="Whether an exam is available")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Exam loaded successfully",
                "student_id": "12345",
                "exam_available": True
            }
        }

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="Exam Management System",
        version="1.0.0",
        description="A system for managing student exams with Telegram integration",
        routes=app.routes,
    )
    
    
    openapi_schema["tags"] = [
        {"name": "Students", "description": "Operations with students"},
        {"name": "Exams", "description": "Operations with exams"},
        {"name": "Telegram", "description": "Telegram bot operations"},
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /start command and verify admin using secret key.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id in verified_admins:
        await update.message.reply_text(
            "Welcome back, Admin! 👋\n\n"
            "Available commands:\n"
            "/upload - Upload a PDF exam file\n"
            "/answer - Set correct answers for the exam\n"
            "/delete - Delete current exam and results\n"
            "/studentlist - View all student results\n"
            "/deletelist - Delete all student results"
        )
        return
    
    await update.message.reply_text(
        "Welcome to the Exam Management Bot! 👋\n"
        "Please enter the admin key to verify yourself and gain admin access."
    )
    
    # Store the user's state to expect a secret key
    context.user_data['expecting_key'] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming messages, including secret key verification.
    """
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text
    
    
    if context.user_data.get('expecting_key', False):
        if message_text == SECRET_KEY:
            verified_admins.add(user_id)
            context.user_data['expecting_key'] = False
            
           
            success_message = (
                "✅ Verification successful! You now have admin access.\n\n"
                "Available commands:\n"
                "/upload - Upload a PDF exam file\n"
                "/answer - Set correct answers for the exam\n"
                "/delete - Delete current exam and results\n"
                "/studentlist - View all student results\n"
                "/deletelist - Delete all student results"
            )
            await update.message.reply_text(success_message)
            
          
            if telegram_app and ADMIN_CHAT_ID_INT and chat_id != ADMIN_CHAT_ID_INT:
                try:
                    group_message = (
                        "🔐 <b>New Admin Verified</b>\n\n"
                        f"Name: {update.effective_user.first_name}\n"
                        f"Username: @{update.effective_user.username if update.effective_user.username else 'N/A'}\n"
                        f"User ID: {user_id}"
                    )
                    await telegram_app.bot.send_message(
                        chat_id=ADMIN_CHAT_ID_INT,
                        text=group_message,
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Failed to send group notification: {str(e)}")
        else:
            await update.message.reply_text("❌ Invalid admin key. Please try again.")
        return


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /upload command."""
    user_id = update.effective_user.id
    if user_id not in verified_admins and update.effective_chat.id != ADMIN_CHAT_ID_INT:
        await update.message.reply_text("You need admin access to use this command.")
        return
    await update.message.reply_text("Please send the exam PDF file.")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle PDF file uploads and extract questions.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    
    if user_id not in verified_admins and chat_id != ADMIN_CHAT_ID_INT:
        logger.warning(f"Unauthorized PDF upload attempt by user {user_id} in chat {chat_id}")
        await update.message.reply_text("You are not authorized to upload PDFs.")
        return
    

    if not update.message.document or not update.message.document.mime_type == 'application/pdf':
        await update.message.reply_text("Please upload a PDF file.")
        return
    
    try:
     
        os.makedirs("uploads", exist_ok=True)
        
    
        os.makedirs("static/js", exist_ok=True)

        file = await context.bot.get_file(update.message.document.file_id)
        pdf_path = os.path.join("uploads", update.message.document.file_name)
        await file.download_to_drive(pdf_path)
        
        logger.info(f"PDF downloaded to: {pdf_path}")
        

        doc = fitz.open(pdf_path)
        text = ""
        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            text += page_text
            logger.info(f"Extracted text from page {page_num+1}, length: {len(page_text)}")
        
        logger.info(f"Total extracted text length: {len(text)}")
        

        global current_exam
        questions = extract_questions_from_text(text)
        current_exam = {
            "raw_text": text,
            "questions": questions
        }
        

        questions_file = os.path.join("static", "js", "exam-questions.js")
        with open(questions_file, 'w', encoding='utf-8') as f:
            f.write(f"const examQuestions = {json.dumps(questions, ensure_ascii=False, indent=2)};")
        
        logger.info(f"Saved {len(questions)} questions to {questions_file}")

        await update.message.reply_text(f"PDF processed successfully. Found {len(questions)} questions.")
        

        logger.info(f"Processed PDF: {update.message.document.file_name}, found {len(questions)} questions")
        
    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        await update.message.reply_text(f"Error processing PDF: {str(e)}")

def extract_questions_from_text(text):
    """
    Extract questions from the PDF text and generate multiple-choice options if needed.
    """
    logger.info("Starting question extraction from text")
    
    # Clean the text by normalizing line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # Split into lines and remove empty lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    logger.info(f"Found {len(lines)} lines in the text")
    
    questions = []
    current_question = None
    current_options = []
    option_letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    question_id = 1
    
    for i, line in enumerate(lines):
        # Check if line is a question (starts with a number)
        if any(line.startswith(f"{num}.") or line.startswith(f"{num})") for num in range(1, 100)):
            # If we have a previous question, save it
            if current_question and current_options:
                questions.append({
                    "id": question_id,
                    "text": current_question,
                    "options": current_options
                })
                logger.info(f"Found question {question_id} with {len(current_options)} options")
                question_id += 1
            
            # Start new question
            current_question = line
            current_options = []
            continue
        
        # Check if line is an option
        is_option = False
        for opt in option_letters:
            if line.lower().startswith(f"{opt}.") or line.lower().startswith(f"{opt})"):
                # Check if this is really an option and not the start of a new question
                # by looking at the content after the option identifier
                option_content = line[2:].strip()
                if option_content and not any(option_content.startswith(f"{num}.") or option_content.startswith(f"{num})") 
                                           for num in range(1, 100)):
                    current_options.append({
                        "id": opt,
                        "text": option_content
                    })
                    is_option = True
                    break
        
        # If line is not an option and we have a current question with options,
        # and the line looks like it might be the start of a new question,
        # save the current question and start a new one
        if not is_option and current_question and current_options:
            if (i + 1 < len(lines) and 
                any(lines[i + 1].lower().startswith(f"{opt}.") or lines[i + 1].lower().startswith(f"{opt})") 
                    for opt in option_letters[:2])):  # Check if next line starts with 'a.' or 'b.'
                questions.append({
                    "id": question_id,
                    "text": current_question,
                    "options": current_options
                })
                logger.info(f"Found question {question_id} with {len(current_options)} options")
                question_id += 1
                current_question = line
                current_options = []
    
    # Add the last question if there is one
    if current_question and current_options:
        questions.append({
            "id": question_id,
            "text": current_question,
            "options": current_options
        })
        logger.info(f"Found final question {question_id} with {len(current_options)} options")
    
    # Validate questions and their options
    validated_questions = []
    for q in questions:
        # Only include questions that have at least 2 options
        if len(q["options"]) >= 2:
            # Sort options by their ID to ensure they're in the correct order
            q["options"] = sorted(q["options"], key=lambda x: x["id"])
            validated_questions.append(q)
            logger.info(f"Question {q['id']} validated with {len(q['options'])} options")
        else:
            logger.warning(f"Skipping question {q['id']} due to insufficient options ({len(q['options'])})")
    
    # If no valid questions were found, create a default question
    if not validated_questions:
        logger.warning("No valid questions found in the PDF, creating a default question")
        validated_questions.append({
            "id": 1,
            "text": "No valid questions found in the PDF. Please upload a different file.",
            "options": [
                {"id": "a", "text": "Option A"},
                {"id": "b", "text": "Option B"}
            ]
        })
    
    logger.info(f"Extracted {len(validated_questions)} valid questions from the text")
    return validated_questions

def generate_multiple_choice_options(question_text):
    """
    Generate multiple-choice options for a question.
    In a real application, you would use an LLM API to generate appropriate options.
    """
    # This is a simplified version that generates generic options
    # In a real application, you would use an LLM API to generate appropriate options
    return [
        { "id": "a", "text": "Option A" },
        { "id": "b", "text": "Option B" },
        { "id": "c", "text": "Option C" },
        { "id": "d", "text": "Option D" }
    ]

async def handle_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        student_id = query.data.split(':')[1]
        if student_id in pending_students:
            try:
                # Move student to approved list
                approved_students[student_id] = pending_students[student_id]
                del pending_students[student_id]
                # Remove from rejected list if they were previously rejected
                rejected_students.discard(student_id)
                
                logger.info(f"Student {student_id} approved successfully")
                await query.edit_message_text(f"Student {student_id} has been approved! ✅")
                return  # Return after successful approval
            except Exception as e:
                logger.error(f"Error approving student {student_id}: {str(e)}")
                await query.edit_message_text(f"Error approving student: {str(e)} ❌")
                raise HTTPException(status_code=500, detail=f"Error approving student: {str(e)}")
        else:
            logger.warning(f"Approval attempt for non-pending student {student_id}")
            await query.edit_message_text("Student not found in pending list. ❌")
            raise HTTPException(status_code=404, detail="Student not found in pending list")
    except Exception as e:
        logger.error(f"Error in handle_approval: {str(e)}")
        await query.edit_message_text("An error occurred during approval ❌")
        raise HTTPException(status_code=500, detail=str(e))

async def handle_rejection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        student_id = query.data.split(':')[1]
        if student_id in pending_students:
            try:
                # Add to rejected list and remove from pending
                rejected_students.add(student_id)
                del pending_students[student_id]
                
                logger.info(f"Student {student_id} rejected successfully")
                await query.edit_message_text(f"Student {student_id} has been rejected. ❌")
            except Exception as e:
                logger.error(f"Error rejecting student {student_id}: {str(e)}")
                await query.edit_message_text(f"Error rejecting student: {str(e)} ❌")
                raise HTTPException(status_code=500, detail=f"Error rejecting student: {str(e)}")
        else:
            logger.warning(f"Rejection attempt for non-pending student {student_id}")
            await query.edit_message_text("Student not found in pending list. ❌")
            raise HTTPException(status_code=404, detail="Student not found in pending list")
    except Exception as e:
        logger.error(f"Error in handle_rejection: {str(e)}")
        await query.edit_message_text("An error occurred during rejection ❌")
        raise HTTPException(status_code=500, detail=str(e))

# Add this function to handle the /answer command in Telegram
async def answer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /answer command to set correct answers for the exam.
    """
    user_id = update.effective_user.id
    if user_id not in verified_admins and update.effective_chat.id != ADMIN_CHAT_ID_INT:
        await update.message.reply_text("You need admin access to use this command.")
        return
    
    # Check if there's an exam loaded
    if not current_exam or not current_exam.get("questions"):
        await update.message.reply_text("No exam is currently loaded. Please upload a PDF first.")
        return
    
    # Get the answers from the command
    if not context.args:
        await update.message.reply_text(
            "Please provide the correct answers for each question.\n"
            "Example: /answer abcabcabcabc (one letter per question)"
        )
        return
    
    # Get the answers string
    answers_str = context.args[0].lower()
    
    # Check if the number of answers matches the number of questions
    if len(answers_str) != len(current_exam["questions"]):
        await update.message.reply_text(
            f"The number of answers ({len(answers_str)}) does not match the number of questions ({len(current_exam['questions'])}).\n"
            f"Please provide exactly {len(current_exam['questions'])} answers."
        )
        return
    
    # Validate that all answers are a, b, c, or d
    valid_answers = set('abcd')
    if not all(answer in valid_answers for answer in answers_str):
        await update.message.reply_text(
            "Invalid answer format. All answers must be a, b, c, or d."
        )
        return
    
    # Store the correct answers
    global correct_answers
    correct_answers = list(answers_str)
    
    # Save the answers to a file
    try:
        answers_file = os.path.join("static", "js", "exam-answers.js")
        with open(answers_file, 'w', encoding='utf-8') as f:
            f.write(f"const examAnswers = {json.dumps(correct_answers, ensure_ascii=False, indent=2)};")
        
        logger.info(f"Saved {len(correct_answers)} answers to {answers_file}")
        
        # Send confirmation messages to both chats
        confirmation = (
            f"✅ Correct answers set successfully for {len(correct_answers)} questions.\n"
            f"Answers: {answers_str}"
        )
        
        # Send to individual chat
        await update.message.reply_text(confirmation)
        
        # Send to group chat if command was used in individual chat
        if telegram_app and ADMIN_CHAT_ID_INT and update.effective_chat.id != ADMIN_CHAT_ID_INT:
            try:
                await telegram_app.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=f"Admin {update.effective_user.first_name} set answers:\n{confirmation}"
                )
            except Exception as e:
                logger.error(f"Failed to send group notification: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error saving answers: {str(e)}")
        await update.message.reply_text(f"Error saving answers: {str(e)}")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /delete command to remove existing exam PDFs and answers.
    """
    user_id = update.effective_user.id
    if user_id not in verified_admins and update.effective_chat.id != ADMIN_CHAT_ID_INT:
        await update.message.reply_text("You need admin access to use this command.")
        return
    
    try:
        # Clear global variables
        global current_exam, correct_answers, student_results
        current_exam = None
        correct_answers = []
        student_results.clear()  # Also clear student results when deleting exam
        
        # Delete PDF files in uploads directory
        uploads_dir = "uploads"
        if os.path.exists(uploads_dir):
            for file in os.listdir(uploads_dir):
                if file.lower().endswith('.pdf'):
                    file_path = os.path.join(uploads_dir, file)
                    os.remove(file_path)
                    logger.info(f"Deleted PDF file: {file_path}")
        
        # Delete exam questions file
        questions_file = os.path.join("static", "js", "exam-questions.js")
        if os.path.exists(questions_file):
            os.remove(questions_file)
            logger.info(f"Deleted questions file: {questions_file}")
        
        # Delete exam answers file
        answers_file = os.path.join("static", "js", "exam-answers.js")
        if os.path.exists(answers_file):
            os.remove(answers_file)
            logger.info(f"Deleted answers file: {answers_file}")
        
        # Send confirmation to both chats
        confirmation = (
            "✅ All exam files and student results have been deleted successfully.\n"
            "You can now upload a new exam using the /upload command."
        )
        
        # Send to individual chat
        await update.message.reply_text(confirmation)
        
        # Send to group chat if command was used in individual chat
        if telegram_app and ADMIN_CHAT_ID_INT and update.effective_chat.id != ADMIN_CHAT_ID_INT:
            try:
                await telegram_app.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=f"Admin {update.effective_user.first_name} deleted all exam files and results."
                )
            except Exception as e:
                logger.error(f"Failed to send group notification: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in delete_command: {str(e)}")
        await update.message.reply_text(f"❌ Error deleting exam files: {str(e)}")

# Initialize Telegram bot
async def init_telegram_bot():
    global telegram_app
    
    # Create the Application and pass it your bot's token
    telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("upload", upload_command))
    telegram_app.add_handler(CommandHandler("answer", answer_command))
    telegram_app.add_handler(CommandHandler("delete", delete_command))
    telegram_app.add_handler(CommandHandler("studentlist", studentlist_command))
    telegram_app.add_handler(CommandHandler("deletelist", deletelist_command))
    
    # Add callback query handlers
    telegram_app.add_handler(CallbackQueryHandler(handle_approval, pattern="^approve:"))
    telegram_app.add_handler(CallbackQueryHandler(handle_rejection, pattern="^reject:"))
    telegram_app.add_handler(CallbackQueryHandler(handle_retake_approval, pattern="^retake_approve:"))
    telegram_app.add_handler(CallbackQueryHandler(handle_retake_rejection, pattern="^retake_reject:"))
    
    # Add document handler for PDF files
    telegram_app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    
    # Add message handler for secret key verification
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start the bot
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    
    logger.info("Telegram bot started successfully")

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/submit-student")
async def submit_student(
    student_id: str = Form(...),
    name: str = Form(...),
    surname: str = Form(...)
):
    try:
        # Validate required fields
        if not student_id or not name or not surname:
            raise HTTPException(
                status_code=400,
                detail="All fields are required. Please fill in all the information."
            )
        
        if student_id in approved_students:
            return RedirectResponse(url="/exam", status_code=303)
        
        if student_id in rejected_students:
            rejected_students.remove(student_id)  # Clear rejection status
        
        # Add to pending list
        pending_students[student_id] = {
            "name": name,
            "surname": surname,
            "student_id": student_id
        }
        
        # Send Telegram notification with Accept and Reject buttons
        keyboard = [
            [
                InlineKeyboardButton("Accept ✅", callback_data=f"approve:{student_id}"),
                InlineKeyboardButton("Reject ❌", callback_data=f"reject:{student_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"New Student Login Request:\nName: {name}\nSurname: {surname}\nStudent ID: {student_id}"
        
        # Use the global telegram_app instead of creating a new one
        if telegram_app:
            try:
                await telegram_app.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=message,
                    reply_markup=reply_markup
                )
                logger.info(f"Sent approval request to admin for student {student_id}")
            except Exception as e:
                logger.error(f"Failed to send Telegram message: {str(e)}")
                # Remove from pending since we couldn't notify admin
                del pending_students[student_id]
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to send approval request: {str(e)}"
                )
        else:
            logger.error("Telegram bot not initialized")
            # Remove from pending since we can't notify admin
            del pending_students[student_id]
            raise HTTPException(
                status_code=500,
                detail="System is not ready to accept requests. Please try again later."
            )
        
        # Redirect to loading page
        return RedirectResponse(url=f"/loading/{student_id}", status_code=303)
        
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error in submit_student: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while processing your request: {str(e)}"
        )

@app.get("/loading/{student_id}", response_class=HTMLResponse)
async def loading_page(request: Request, student_id: str):
    return templates.TemplateResponse("loading.html", {
        "request": request,
        "student_id": student_id
    })

@app.get("/check-approval/{student_id}")
async def check_approval(student_id: str):
    try:
        # Log the current state for debugging
        logger.debug(f"Checking status for student {student_id}")
        logger.debug(f"Pending students: {list(pending_students.keys())}")
        logger.debug(f"Approved students: {list(approved_students.keys())}")
        logger.debug(f"Rejected students: {list(rejected_students)}")
        
        if student_id in approved_students:
            logger.info(f"Status check: Student {student_id} is approved")
            return {"status": "approved", "message": "Your request has been approved"}
        elif student_id in rejected_students:
            logger.info(f"Status check: Student {student_id} is rejected")
            return {"status": "rejected", "message": "Your request has been rejected"}
        elif student_id in pending_students:
            logger.info(f"Status check: Student {student_id} is pending")
            return {"status": "pending", "message": "Waiting for admin approval"}
        else:
            logger.warning(f"Status check: Student {student_id} not found in any list")
            raise HTTPException(
                status_code=404, 
                detail="Student not found. Please submit the form again."
            )
    except Exception as e:
        logger.error(f"Error checking approval status for student {student_id}: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="An error occurred while checking your status. Please try again."
        )

@app.get("/error")
async def error_page(request: Request, message: str = Query(..., description="Error message to display")):
    """
    Display a user-friendly error page.
    
    Args:
        request: The FastAPI request object
        message: The error message to display
        
    Returns:
        HTMLResponse: The rendered error page
    """
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error_message": message}
    )

@app.get("/exam")
async def exam_page(request: Request, student_id: Optional[str] = None):
    """
    Display the exam page for a student.
    """
    try:
        # Check if there's an exam available
        if not current_exam:
            # Try to load an existing PDF
            await load_existing_pdf()
            
            if not current_exam:
                return templates.TemplateResponse(
                    "error.html",
                    {"request": request, "error": "No exam is currently available. Please check back later."}
                )
        
        # If no student ID is provided, show the login form
        if not student_id:
            return templates.TemplateResponse(
                "login.html",
                {"request": request}
            )
        
        # Validate student ID
        if student_id not in approved_students:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Your Student ID is not approved for this exam. Please contact your administrator."}
            )
        
        # Check if student has already taken the exam
        if student_id in student_attempts and student_attempts[student_id].get("completed", False):
            # Get student information
            student = approved_students[student_id]
            
            # If there's a pending retake request, redirect to loading page
            if student_attempts[student_id].get("retake_pending", False):
                return RedirectResponse(url=f"/retake-loading/{student_id}", status_code=303)
            
            # Send retake request to admin group
            keyboard = [
                [
                    InlineKeyboardButton("Allow Retake ✅", callback_data=f"retake_approve:{student_id}"),
                    InlineKeyboardButton("Reject Retake ❌", callback_data=f"retake_reject:{student_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "🔄 <b>Exam Retake Request</b>\n\n"
                f"Student is attempting to retake the exam:\n"
                f"Name: {student['name']}\n"
                f"Surname: {student['surname']}\n"
                f"Student ID: {student_id}\n\n"
                f"Previous attempt score: {student_results.get(student_id, {}).get('correct', 0)}/{len(current_exam['questions'])}"
            )
            
            if telegram_app:
                try:
                    await telegram_app.bot.send_message(
                        chat_id=ADMIN_CHAT_ID_INT,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                    # Mark that there's a pending retake request
                    student_attempts[student_id]["retake_pending"] = True
                    # Redirect to retake loading page
                    return RedirectResponse(url=f"/retake-loading/{student_id}", status_code=303)
                except Exception as e:
                    logger.error(f"Failed to send retake request: {str(e)}")
            
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Failed to send retake request. Please try again later."}
            )
        
        # Get student information
        student = approved_students[student_id]
        
        # Return the exam page
        return templates.TemplateResponse(
            "exam.html",
            {
                "request": request,
                "student_id": student_id,
                "student_name": student["name"],
                "student_surname": student["surname"]
            }
        )
    except Exception as e:
        logger.error(f"Error in exam_page: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"An error occurred: {str(e)}"}
        )

@app.get("/retake-loading/{student_id}", response_class=HTMLResponse)
async def retake_loading_page(request: Request, student_id: str):
    """
    Display the loading page while waiting for retake approval.
    """
    try:
        if student_id not in approved_students:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Invalid student ID."}
            )
        
        student = approved_students[student_id]
        return templates.TemplateResponse(
            "retake-loading.html",
            {
                "request": request,
                "student_id": student_id,
                "student_name": student["name"],
                "student_surname": student["surname"]
            }
        )
    except Exception as e:
        logger.error(f"Error in retake_loading_page: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"An error occurred: {str(e)}"}
        )

@app.get("/check-retake-approval/{student_id}")
async def check_retake_approval(student_id: str):
    """
    Check if a student's retake request has been approved.
    """
    try:
        if student_id not in student_attempts:
            return {"status": "error", "message": "Student not found"}
        
        student_attempt = student_attempts[student_id]
        
        if not student_attempt.get("retake_pending", False) and not student_attempt.get("completed", True):
            # Retake was approved (retake_pending is False and completed is False)
            return {"status": "approved", "message": "Your retake request has been approved"}
        elif not student_attempt.get("retake_pending", False) and student_attempt.get("completed", True):
            # Retake was rejected (retake_pending is False but completed is still True)
            return {"status": "rejected", "message": "Your retake request has been rejected"}
        else:
            # Still pending
            return {"status": "pending", "message": "Waiting for admin approval"}
            
    except Exception as e:
        logger.error(f"Error checking retake approval for student {student_id}: {str(e)}")
        return {"status": "error", "message": "An error occurred while checking your status"}

@app.get("/api/exam")
async def get_exam():
    """
    Get the current exam questions.
    
    Returns:
        Dict: The current exam questions or an error message
    """
    try:
        if not current_exam:
            # Try to load an existing PDF
            await load_existing_pdf()
            
            if not current_exam:
                return JSONResponse(
                    status_code=404,
                    content={"error": "No exam is currently available. Please check back later."}
                )
        
        return current_exam
    except Exception as e:
        logger.error(f"Error in get_exam: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"An error occurred while retrieving the exam: {str(e)}"}
        )

async def send_telegram_message(message: str):
    """Send a message to the admin chat via Telegram."""
    try:
        await telegram_app.bot.send_message(
            chat_id=ADMIN_CHAT_ID_INT,
            text=message,
            parse_mode='HTML'
        )
        logger.info("Telegram message sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {str(e)}")
        raise

@app.post("/submit-exam")
async def submit_exam(
    student_id: str = Form(...),
    answers: str = Form(...)
):
    """
    Submit exam answers for a student.
    """
    try:
        # Validate required fields
        if not student_id or not answers:
            raise HTTPException(
                status_code=400,
                detail="Student ID and answers are required."
            )
        
        if student_id not in approved_students:
            raise HTTPException(
                status_code=403,
                detail="Your Student ID is not approved for this exam. Please contact your administrator."
            )
        
        # Mark the exam as completed for this student
        if student_id not in student_attempts:
            student_attempts[student_id] = {}
        student_attempts[student_id]["completed"] = True
        student_attempts[student_id]["retake_pending"] = False
        
        # Parse the JSON answers
        try:
            answers_data = json.loads(answers)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid answer format. Please try again."
            )
        
        # Get student information
        student = approved_students[student_id]
        
        # Check answers if correct_answers are available
        correct_count = 0
        incorrect_count = 0
        student_answers = []
        
        if correct_answers and current_exam and current_exam.get("questions"):
            for i, question in enumerate(current_exam["questions"]):
                question_id = str(question["id"])
                student_answer = answers_data.get(question_id, "")
                student_answers.append(student_answer)  # Store the actual answer
                
                # Check if the answer is correct
                is_correct = False
                if i < len(correct_answers):
                    is_correct = student_answer == correct_answers[i]
                    if is_correct:
                        correct_count += 1
                    else:
                        incorrect_count += 1
        
        # Store the results including the actual answers
        global student_results
        student_results[student_id] = {
            "correct": correct_count,
            "incorrect": incorrect_count,
            "total": len(current_exam["questions"]),
            "answers": student_answers,  # Store the actual answers
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Format answers for Telegram message
        formatted_answers = "📝 <b>Exam Submission Received</b>\n\n"
        formatted_answers += f"👤 <b>Student Information:</b>\n"
        formatted_answers += f"Name: {student['name']}\n"
        formatted_answers += f"Surname: {student['surname']}\n"
        formatted_answers += f"Student ID: {student_id}\n\n"
        
        # Add score information if available
        if correct_answers:
            formatted_answers += f"📊 <b>Score:</b> {correct_count}/{len(current_exam['questions'])} ({correct_count/len(current_exam['questions'])*100:.1f}%)\n\n"
        
        formatted_answers += "📋 <b>Answers:</b>\n"
        
        # Add each question and answer to the formatted message
        for i, question in enumerate(current_exam["questions"]):
            question_id = str(question["id"])
            student_answer = answers_data.get(question_id, "")
            
            # Find the answer text
            answer_text = "Not answered"
            for opt in question["options"]:
                if opt["id"] == student_answer:
                    answer_text = f"{opt['id'].upper()}. {opt['text']}"
                    break
            
            # Check if the answer is correct
            is_correct = False
            if i < len(correct_answers):
                is_correct = student_answer == correct_answers[i]
            
            formatted_answers += f"\n<b>Q{question_id}:</b> {question['text']}\n"
            formatted_answers += f"<b>A:</b> {answer_text} {'✅' if is_correct else '❌'}\n"
        
        # Send notification to admin
        await send_telegram_message(formatted_answers)
        
        # Return success with redirect to results page
        return RedirectResponse(
            url=f"/results/{student_id}?correct={correct_count}&incorrect={incorrect_count}",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in submit_exam: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred while submitting your exam: {str(e)}"
        )

# Startup event to initialize the Telegram bot
@app.on_event("startup")
async def startup_event():
    # Start the Telegram bot in the background
    asyncio.create_task(init_telegram_bot())
    
    # Load any existing PDF from the uploads folder
    await load_existing_pdf()
    
    # Load any existing answers
    await load_existing_answers()
    
    logger.info("Application startup complete")

async def load_existing_pdf():
    """
    Load any existing PDF from the uploads folder on startup.
    """
    try:
        # Check if the uploads directory exists
        if not os.path.exists("uploads"):
            logger.warning("Uploads directory does not exist")
            return
        
        # Get all PDF files in the uploads directory
        pdf_files = [f for f in os.listdir("uploads") if f.lower().endswith('.pdf')]
        
        if not pdf_files:
            logger.warning("No PDF files found in the uploads directory")
            return
        
        # Use the most recent PDF file
        pdf_file = pdf_files[-1]  # Get the last file (most recent)
        pdf_path = os.path.join("uploads", pdf_file)
        
        logger.info(f"Loading existing PDF: {pdf_path}")
        
        # Extract text from the PDF
        doc = fitz.open(pdf_path)
        text = ""
        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            text += page_text
            logger.info(f"Extracted text from page {page_num+1}, length: {len(page_text)}")
        
        logger.info(f"Total extracted text length: {len(text)}")
        
        # Extract questions from the text
        global current_exam
        questions = extract_questions_from_text(text)
        current_exam = {
            "raw_text": text,
            "questions": questions
        }
        
        # Save the questions to a JSON file for the frontend
        questions_file = os.path.join("static", "js", "exam-questions.js")
        with open(questions_file, 'w', encoding='utf-8') as f:
            f.write(f"const examQuestions = {json.dumps(questions, ensure_ascii=False, indent=2)};")
        
        logger.info(f"Saved {len(questions)} questions to {questions_file}")
        logger.info(f"Loaded PDF: {pdf_file}, found {len(questions)} questions")
        
    except Exception as e:
        logger.error(f"Error loading existing PDF: {str(e)}")

# Add a function to load correct answers on startup
async def load_existing_answers():
    """
    Load any existing answers from the answers file on startup.
    """
    try:
        answers_file = os.path.join("static", "js", "exam-answers.js")
        if os.path.exists(answers_file):
            with open(answers_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Extract the answers array from the JavaScript file
                import re
                match = re.search(r'const examAnswers = (\[.*?\]);', content, re.DOTALL)
                if match:
                    answers_str = match.group(1)
                    global correct_answers
                    correct_answers = json.loads(answers_str)
                    logger.info(f"Loaded {len(correct_answers)} answers from {answers_file}")
    except Exception as e:
        logger.error(f"Error loading existing answers: {str(e)}")

# Shutdown event to stop the Telegram bot
@app.on_event("shutdown")
async def shutdown_event():
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()
        logger.info("Telegram bot stopped")

# Add a route for the results page
@app.get("/results/{student_id}")
async def results_page(
    request: Request,
    student_id: str,
    correct: int = Query(0),
    incorrect: int = Query(0)
):
    """
    Display the exam results page for a student.
    """
    try:
        # Check if the student is approved
        if student_id not in approved_students:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "Your Student ID is not approved. Please contact your administrator."}
            )
        
        # Get student information
        student = approved_students[student_id]
        
        # Check if there's an exam available
        if not current_exam or not current_exam.get("questions"):
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "error": "No exam is currently available."}
            )
        
        # Get the questions and answers
        questions = current_exam["questions"]
        total_questions = len(questions)
        
        # Get student's results from stored data
        student_result = student_results.get(student_id, {})
        student_answers = student_result.get("answers", [])
        
        # Prepare question details for display
        question_details = []
        for i, question in enumerate(questions):
            question_id = str(question["id"])
            
            # Get the student's actual answer and answer text
            student_answer = "Not answered"
            correct_answer = "Unknown"
            is_correct = False
            
            # Get student's actual answer for this question
            if i < len(student_answers):
                answer_id = student_answers[i]
                # Find the answer text for both student's answer and correct answer
                for opt in question["options"]:
                    # For student's answer
                    if opt["id"] == answer_id:
                        student_answer = f"{opt['id'].upper()}. {opt['text']}"
                    # For correct answer
                    if i < len(correct_answers) and opt["id"] == correct_answers[i]:
                        correct_answer = f"{opt['id'].upper()}. {opt['text']}"
                        if answer_id == correct_answers[i]:
                            is_correct = True
            
            question_details.append({
                "text": question["text"],
                "student_answer": student_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct
            })
        
        # Return the results page
        return templates.TemplateResponse(
            "results.html",
            {
                "request": request,
                "student_id": student_id,
                "student_name": student["name"],
                "student_surname": student["surname"],
                "correct_answers": correct,
                "incorrect_answers": incorrect,
                "total_questions": total_questions,
                "questions": question_details
            }
        )
    except Exception as e:
        logger.error(f"Error in results_page: {str(e)}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": f"An error occurred: {str(e)}"}
        )

async def studentlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /studentlist command to display all student results.
    """
    user_id = update.effective_user.id
    if user_id not in verified_admins and update.effective_chat.id != ADMIN_CHAT_ID_INT:
        await update.message.reply_text("You need admin access to use this command.")
        return
    
    try:
        if not student_results:
            await update.message.reply_text("No student results available.")
            return
        
        # Format the student list message
        message = "📊 <b>Student Exam Results</b>\n\n"
        
        for student_id, result in student_results.items():
            student = approved_students.get(student_id, {})
            message += f"👤 <b>Student Information:</b>\n"
            message += f"Name: {student.get('name', 'N/A')} {student.get('surname', 'N/A')}\n"
            message += f"ID: {student_id}\n"
            message += f"Score: {result['correct']}/{result['total']} ({(result['correct']/result['total']*100):.1f}%)\n"
            message += f"Correct: {result['correct']}\n"
            message += f"Incorrect: {result['incorrect']}\n"
            message += "------------------------\n\n"
        
        await update.message.reply_text(message, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error in studentlist_command: {str(e)}")
        await update.message.reply_text(f"❌ Error retrieving student list: {str(e)}")

async def deletelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /deletelist command to clear all student results.
    """
    user_id = update.effective_user.id
    if user_id not in verified_admins and update.effective_chat.id != ADMIN_CHAT_ID_INT:
        await update.message.reply_text("You need admin access to use this command.")
        return
    
    try:
        # Clear the student results
        global student_results
        student_results.clear()
        
        await update.message.reply_text("✅ All student results have been deleted successfully.")
        
    except Exception as e:
        logger.error(f"Error in deletelist_command: {str(e)}")
        await update.message.reply_text(f"❌ Error deleting student results: {str(e)}")

# Add these new handlers to init_telegram_bot()
async def handle_retake_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle approval of exam retake requests."""
    query = update.callback_query
    await query.answer()
    
    try:
        student_id = query.data.split(':')[1]
        if student_id in student_attempts:
            # Clear the previous attempt
            student_attempts[student_id]["completed"] = False
            student_attempts[student_id]["retake_pending"] = False
            # Optionally clear previous results
            if student_id in student_results:
                del student_results[student_id]
            
            await query.edit_message_text(
                f"Retake approved for student {student_id}. ✅\n"
                "They can now take the exam again."
            )
        else:
            await query.edit_message_text("Student not found in attempts list. ❌")
    except Exception as e:
        logger.error(f"Error in handle_retake_approval: {str(e)}")
        await query.edit_message_text("An error occurred during retake approval ❌")

async def handle_retake_rejection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle rejection of exam retake requests."""
    query = update.callback_query
    await query.answer()
    
    try:
        student_id = query.data.split(':')[1]
        if student_id in student_attempts:
            student_attempts[student_id]["retake_pending"] = False
            await query.edit_message_text(
                f"Retake rejected for student {student_id}. ❌\n"
                "They will not be allowed to take the exam again."
            )
        else:
            await query.edit_message_text("Student not found in attempts list. ❌")
    except Exception as e:
        logger.error(f"Error in handle_retake_rejection: {str(e)}")
        await query.edit_message_text("An error occurred during retake rejection ❌")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 
