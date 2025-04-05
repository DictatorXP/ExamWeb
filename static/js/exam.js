// Exam functionality
document.addEventListener('DOMContentLoaded', function() {
    // Store user answers
    const userAnswers = {};
    
    // Update progress bar
    function updateProgress() {
        const totalQuestions = examQuestions.length;
        const answeredCount = Object.keys(userAnswers).length;
        const progressPercentage = (answeredCount / totalQuestions) * 100;
        
        document.getElementById('progress-fill').style.width = `${progressPercentage}%`;
        document.getElementById('answered-count').textContent = answeredCount;
        document.getElementById('total-questions').textContent = totalQuestions;
    }
    
    // Generate the exam questions
    function generateExam() {
        const container = document.getElementById('questions-container');
        
        examQuestions.forEach(question => {
            const questionElement = document.createElement('div');
            questionElement.className = 'question-container unanswered';
            questionElement.id = `question-${question.id}`;
            
            const questionText = document.createElement('div');
            questionText.className = 'question-text';
            questionText.textContent = `${question.id}. ${question.text}`;
            
            const optionsContainer = document.createElement('div');
            optionsContainer.className = 'options-container';
            
            question.options.forEach(option => {
                const optionItem = document.createElement('div');
                optionItem.className = 'option-item';
                optionItem.dataset.questionId = question.id;
                optionItem.dataset.optionId = option.id;
                
                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = `question-${question.id}`;
                radio.value = option.id;
                radio.className = 'option-radio';
                radio.id = `option-${question.id}-${option.id}`;
                
                const label = document.createElement('label');
                label.htmlFor = `option-${question.id}-${option.id}`;
                label.textContent = `${option.id}. ${option.text}`;
                
                optionItem.appendChild(radio);
                optionItem.appendChild(label);
                
                // Add click event to select the option
                optionItem.addEventListener('click', () => {
                    // Unselect all options for this question
                    document.querySelectorAll(`input[name="question-${question.id}"]`).forEach(input => {
                        input.checked = false;
                        input.parentElement.classList.remove('selected');
                    });
                    
                    // Select the clicked option
                    radio.checked = true;
                    optionItem.classList.add('selected');
                    
                    // Store the answer
                    userAnswers[question.id] = option.id;
                    
                    // Update the question container class
                    questionElement.classList.remove('unanswered');
                    questionElement.classList.add('answered');
                    
                    // Update progress
                    updateProgress();
                });
                
                optionsContainer.appendChild(optionItem);
            });
            
            questionElement.appendChild(questionText);
            questionElement.appendChild(optionsContainer);
            container.appendChild(questionElement);
        });
        
        // Initialize progress
        updateProgress();
    }
    
    // Validate answers before submission
    function validateAnswers() {
        const validationMessage = document.getElementById('validation-message');
        const unansweredQuestions = [];
        
        // Check if all questions are answered
        examQuestions.forEach(question => {
            if (!userAnswers[question.id]) {
                unansweredQuestions.push(question.id);
                document.getElementById(`question-${question.id}`).classList.add('unanswered');
                document.getElementById(`question-${question.id}`).classList.remove('answered');
            }
        });
        
        if (unansweredQuestions.length > 0) {
            // Show error message
            validationMessage.textContent = `Please answer all questions! Unanswered questions: ${unansweredQuestions.join(', ')}`;
            validationMessage.className = 'validation-message error';
            
            // Scroll to the first unanswered question
            document.getElementById(`question-${unansweredQuestions[0]}`).scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
            
            return false;
        } else {
            // Show success message
            validationMessage.textContent = 'All questions answered! You can now submit the exam.';
            validationMessage.className = 'validation-message success';
            return true;
        }
    }
    
    // Handle form submission
    async function handleSubmit(event) {
        event.preventDefault();
        
        // Validate answers first
        if (!validateAnswers()) {
            return;
        }
        
        const formData = new FormData(event.target);
        
        // Add answers to form data
        formData.append('answers', JSON.stringify(userAnswers));
        
        try {
            const response = await fetch('/submit-exam', {
                method: 'POST',
                body: formData
            });
            
            // Try to parse the response as JSON
            let data;
            try {
                data = await response.json();
            } catch (e) {
                console.error('Failed to parse response as JSON:', e);
                throw new Error('Server returned an invalid response format');
            }
            
            // Handle different response statuses
            if (!response.ok) {
                // Server returned an error with a message
                const errorMessage = data.detail || data.message || `Server error: ${response.status}`;
                console.error('Server error:', errorMessage);
                alert(`Error: ${errorMessage}`);
                return;
            }
            
            // Handle successful response
            if (data.status === 'success') {
                alert('Your exam has been submitted successfully!');
                window.location.href = '/';
            } else {
                console.log('Unexpected response:', data);
                alert('Your exam was submitted, but received an unexpected response from the server.');
            }
        } catch (error) {
            // Handle network errors or other exceptions
            console.error('Error during exam submission:', error);
            alert(`Error: ${error.message || 'Network error. Please check your connection and try again.'}`);
        }
    }
    
    // Add event listeners
    document.getElementById('examForm').addEventListener('submit', handleSubmit);
    document.getElementById('validate-btn').addEventListener('click', validateAnswers);
    
    // Initialize the exam
    generateExam();
}); 