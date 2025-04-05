# Exam Management System

A web-based exam management system with Telegram integration for administering online exams and managing student submissions.

## Features

### Admin Features (via Telegram Bot)
- **Admin Authentication**: Secure admin verification using a secret key
- **PDF Exam Management**:
  - Upload PDF exam files
  - Automatic question and option extraction
  - Support for varying numbers of options (2-7) per question
  - Set correct answers for automatic grading
- **Student Management**:
  - Approve/reject student registration requests
  - View student exam results
  - Manage retake requests
  - Delete student results
- **Exam Control**:
  - Delete current exam and results
  - View comprehensive student performance list

### Student Features (via Web Interface)
- **Registration**: Submit student information for admin approval
- **Exam Taking**:
  - Take exams with multiple-choice questions
  - Clear interface for selecting answers
  - Real-time progress tracking
- **Results**:
  - Immediate score display after submission
  - Detailed feedback on correct/incorrect answers
  - Option to request exam retakes

## Setup

### Prerequisites
- Python 3.7+
- FastAPI
- Telegram Bot Token
- PostgreSQL (optional, currently using in-memory storage)

### Environment Variables
Create a `.env` file in the root directory with:
```
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=your_admin_group_chat_id
SECRET_KEY=your_admin_secret_key
```

### Installation
1. Clone the repository:
```bash
git clone <repository_url>
cd exam-management-system
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start the application:
```bash
python main.py
```

The server will start on `http://localhost:8000`

## Usage

### Admin Setup
1. Start the Telegram bot with `/start`
2. Enter the admin secret key for verification
3. Use the following commands:
   - `/upload` - Upload a PDF exam file
   - `/answer` - Set correct answers (e.g., `/answer abcabd`)
   - `/delete` - Delete current exam
   - `/studentlist` - View all results
   - `/deletelist` - Clear all results

### Student Flow
1. Access the web interface
2. Submit registration with student ID, name, and surname
3. Wait for admin approval
4. Take the exam when approved
5. View results immediately after submission
6. Request retake if needed (requires admin approval)

### Exam Format
- PDF files should have clearly numbered questions
- Options should be marked with letters (a, b, c, etc.)
- Each question can have 2-7 options
- Questions can have varying numbers of options

## Security Features
- Admin verification through secret key
- Student approval system
- Secure exam retake management
- Protected admin commands
- Telegram group notifications for important events

## Technical Details
- Built with FastAPI for high performance
- Real-time Telegram integration
- PDF text extraction using PyMuPDF
- Automatic question parsing
- Responsive web interface
- In-memory data storage (can be extended to use a database)

## Error Handling
- Comprehensive logging system
- User-friendly error messages
- Graceful failure handling
- Automatic PDF reload on startup

## Future Improvements
- Database integration for persistent storage
- Multiple exam support
- Timed exams
- Rich text question support
- Image question support
- Advanced analytics dashboard
- Student result export functionality

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

 
