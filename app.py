from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
from mood_analysis import analyze_sentiment
import os
import random

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///emoticare.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

class MoodLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    mood = db.Column(db.String(20))
    tags = db.Column(db.String(100))
    date = db.Column(db.Date)

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    entry = db.Column(db.Text)
    sentiment = db.Column(db.String(20))
    date = db.Column(db.Date)

# Create database tables within application context
with app.app_context():
    db.create_all()

@app.route("/")
def welcome():
    return render_template("welcome.html")


@app.route('/')
def home():
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        
        if User.query.filter_by(email=email).first():
            return 'Email already registered.'
        
        new_user = User(name=name, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['name'] = user.name
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='Invalid email or password.')

    return render_template('login.html')


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    return render_template('dashboard.html', name=session['name'])

@app.route('/log_mood', methods=['GET', 'POST'])
def log_mood():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        mood = request.form['mood']
        tags = request.form.get('tags', '')
        new_log = MoodLog(user_id=session['user_id'], mood=mood, tags=tags, date=date.today())
        db.session.add(new_log)
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('log_mood.html')

@app.route('/journal', methods=['GET', 'POST'])
def journal():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        entry = request.form['entry']
        sentiment = analyze_sentiment(entry)
        journal = JournalEntry(user_id=session['user_id'], entry=entry, sentiment=sentiment, date=date.today())
        db.session.add(journal)
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('journal.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/progress')
def progress():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    # Fetch mood logs
    mood_data = MoodLog.query.filter_by(user_id=session['user_id']).all()
    mood_counts = {}
    for log in mood_data:
        mood_counts[log.mood] = mood_counts.get(log.mood, 0) + 1

    # Fetch journal sentiments by date
    journal_data = JournalEntry.query.filter_by(user_id=session['user_id']).all()
    dates = []
    sentiments = []
    for entry in journal_data:
        dates.append(entry.date.strftime('%Y-%m-%d'))
        sentiments.append(entry.sentiment)

    return render_template('progress.html', mood_counts=mood_counts, dates=dates, sentiments=sentiments)

# Chatbot route
@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        return jsonify({'reply': "Please log in to chat with Riya."})

    user_msg = request.json.get('message', '').lower()

    # Initialize session variables for conversation state and history
    if 'chat_history' not in session:
        session['chat_history'] = []
    if 'conversation_state' not in session:
        session['conversation_state'] = 'greeting'
    if 'last_topic' not in session:
        session['last_topic'] = None

    session['chat_history'].append(user_msg)
    session['chat_history'] = session['chat_history'][-5:]  # Keep last 5 messages for context

    # Fetch user data for context
    recent_mood = MoodLog.query.filter_by(user_id=session['user_id']).order_by(MoodLog.date.desc()).first()
    recent_journal = JournalEntry.query.filter_by(user_id=session['user_id']).order_by(JournalEntry.date.desc()).first()
    mood_context = recent_mood.mood.lower() if recent_mood else None
    sentiment_context = recent_journal.sentiment.lower() if recent_journal else None

    # Analyze sentiment of the current message
    msg_sentiment = analyze_sentiment(user_msg)

    # Define conversation states and transitions
    current_state = session['conversation_state']
    next_state = current_state  # Default to stay in current state

    # Expanded keyword and intent detection
    greetings = ['hi', 'hello', 'hey', 'yo', 'good morning', 'good evening']
    farewells = ['bye', 'goodbye', 'see you', 'later']
    mood_keywords = {
        'sad': ['sad', 'unhappy', 'depressed', 'down', 'low'],
        'happy': ['happy', 'good', 'great', 'awesome', 'fantastic'],
        'stress': ['stress', 'anxious', 'worried', 'nervous', 'overwhelmed'],
        'tired': ['tired', 'exhausted', 'sleepy'],
        'angry': ['angry', 'mad', 'frustrated', 'annoyed']
    }
    question_indicators = ['what', 'how', 'why', 'can you', 'do you', 'tell me']
    activity_requests = ['suggest', 'help', 'idea', 'what can i do', 'activity']

    # Helper function to check for keywords
    def contains_keywords(text, keywords):
        return any(word in text for word in keywords)

    # Response variations for a more human-like tone
    sad_responses = [
        "I’m really sorry to hear you’re feeling this way, {}. Let’s work through this together—would you like to talk more about what’s going on?",
        "Oh, {}, I can feel how tough this is for you. How about we try something to lift your spirits?",
        "I’m here for you, {}. It sounds like a hard day—do you want to share more or try a calming activity?"
    ]
    happy_responses = [
        "Yay, {}! I love hearing that you’re feeling so good! What’s making you smile today?",
        "That’s so awesome, {}! Your happiness is infectious—want to tell me more?",
        "I’m thrilled for you, {}! Keep that positive energy going—maybe we can celebrate with some fun?"
    ]
    stress_responses = [
        "I can sense how overwhelming things might be for you, {}. Let’s take a moment to relax—how about a calming activity?",
        "Stress can be so tough, {}. I’m here to help—would you like to try something to unwind?",
        "I’m sorry you’re feeling stressed, {}. Let’s find a way to ease that tension—what do you think?"
    ]
    tired_responses = [
        "You sound really tired, {}. Have you had a chance to rest today? Let’s find something soothing for you.",
        "I feel you, {}—being tired can be rough. How about we try something to help you recharge?",
        "Oh, {}, you must be exhausted. Let’s take it easy—want to try a relaxing activity?"
    ]
    question_responses = [
        "That’s a great question, {}! Let me help with that—",
        "I’m happy to answer that for you, {}. Here’s what I think—",
        "Good one, {}! Let’s figure that out together—"
    ]

    # Mood-based activity, playlist, and song recommendations
    recommendations = {
        'sad': {
            'activities': [
                "a gratitude exercise—can you name three things you’re thankful for today?",
                "writing in your journal to express how you’re feeling?",
                "a short walk outside to enjoy some fresh air?"
            ],
            'playlists': [
                "a soothing playlist like 'Calm Vibes' to help you relax",
                "a gentle acoustic playlist like 'Soft Melodies' to lift your spirits"
            ],
            'songs': [
                "'Somewhere Over the Rainbow' by Israel Kamakawiwo'ole—it’s really comforting",
                "'Hallelujah' by Leonard Cohen—it might resonate with how you’re feeling"
            ]
        },
        'happy': {
            'activities': [
                "capturing this moment in your journal to look back on later?",
                "a quick dance break to celebrate your good mood?",
                "sharing your happiness with a friend—maybe give them a call?"
            ],
            'playlists': [
                "an upbeat playlist like 'Feel Good Hits' to keep the energy up",
                "a pop playlist like 'Happy Days' to match your vibe"
            ],
            'songs': [
                "'Walking on Sunshine' by Katrina and the Waves—it’s super cheerful!",
                "'Happy' by Pharrell Williams—it’s perfect for your mood!"
            ]
        },
        'stress': {
            'activities': [
                "a breathing exercise: inhale for 4 seconds, hold for 4, and exhale for 4—ready to try it?",
                "a short mindfulness meditation to help you relax?",
                "writing down what’s stressing you in your journal to clear your mind?"
            ],
            'playlists': [
                "a calming playlist like 'Stress Relief' to help you unwind",
                "a nature sounds playlist like 'Peaceful Forest' to soothe your nerves"
            ],
            'songs': [
                "'Clair de Lune' by Claude Debussy—it’s really calming",
                "'Weightless' by Marconi Union—it’s known for reducing stress"
            ]
        },
        'tired': {
            'activities': [
                "imagining a peaceful place—like a beach or forest—can you describe it to me?",
                "a short nap to help you recharge?",
                "some gentle stretching to relax your body?"
            ],
            'playlists': [
                "a relaxing playlist like 'Sleepy Tunes' to help you rest",
                "a lo-fi playlist like 'Chill Beats' to wind down"
            ],
            'songs': [
                "'Moon River' by Audrey Hepburn—it’s so soothing",
                "'Lullaby' by Brahms—it might help you drift off"
            ]
        },
        'angry': {
            'activities': [
                "writing down what’s making you angry in your journal to let it out?",
                "a quick physical activity like jumping jacks to release some tension?",
                "a deep breathing exercise to help you calm down?"
            ],
            'playlists': [
                "a high-energy playlist like 'Power Up' to channel your emotions",
                "a calming playlist like 'Cool Down' to help you relax"
            ],
            'songs': [
                "'Sweet Child O’ Mine' by Guns N’ Roses—it might help you channel that energy",
                "'Let It Be' by The Beatles—to help you find some peace"
            ]
        }
    }

    # Default reply
    reply = f"I’m here for you, {session.get('name', '')}. Tell me more about how you’re feeling."

    # State machine for conversation flow
    if current_state == 'greeting':
        if contains_keywords(user_msg, greetings):
            reply = f"Hi there, {sessionssion.get('name', '')}! I’m Riya, your wellness buddy. "
            if mood_context:
                reply += f"I noticed you’ve been feeling {mood_context} lately—how are you doing right now?"
            else:
                reply += "How’s your day going so far?"
            next_state = 'emotional_checkin'
        elif contains_keywords(user_msg, farewells):
            reply = f"Take care, {session.get('name', '')}! I’ll be here whenever you need me. 🌟"
            next_state = 'farewell'
        else:
            reply = f"Hey {session.get('name', '')}, I didn’t quite catch that. How can I help you today?"
            next_state = 'emotional_checkin'

    elif current_state == 'emotional_checkin':
        if contains_keywords(user_msg, mood_keywords['sad']):
            reply = random.choice(sad_responses).format(session.get('name', ''))
            next_state = 'suggestion'
            session['last_topic'] = 'sad'
        elif contains_keywords(user_msg, mood_keywords['happy']):
            reply = random.choice(happy_responses).format(session.get('name', ''))
            next_state = 'suggestion'
            session['last_topic'] = 'happy'
        elif contains_keywords(user_msg, mood_keywords['stress']):
            reply = random.choice(stress_responses).format(session.get('name', ''))
            next_state = 'suggestion'
            session['last_topic'] = 'stress'
        elif contains_keywords(user_msg, mood_keywords['tired']):
            reply = random.choice(tired_responses).format(session.get('name', ''))
            next_state = 'suggestion'
            session['last_topic'] = 'tired'
        elif contains_keywords(user_msg, mood_keywords['angry']):
            reply = f"I can tell you’re feeling frustrated, {session.get('name', '')}. Let’s find a way to ease that—want to try something to help you calm down?"
            next_state = 'suggestion'
            session['last_topic'] = 'angry'
        elif contains_keywords(user_msg, question_indicators):
            reply = random.choice(question_responses).format(session.get('name', ''))
            if 'how are you' in user_msg:
                reply += "I’m doing great, thanks for asking! More importantly, how are *you* feeling?"
            elif 'what can i do' in user_msg:
                reply += "How about we try a quick mindfulness exercise, or would you like to journal your thoughts?"
            else:
                reply += "Can you tell me a bit more so I can help you better?"
            next_state = 'engagement'
        elif contains_keywords(user_msg, farewells):
            reply = f"See you soon, {session.get('name', '')}! I’m always here if you need to chat. 🌟"
            next_state = 'farewell'
        else:
            # Use sentiment analysis to guide the response
            if msg_sentiment == 'Negative':
                reply = f"It sounds like you might be feeling a bit down, {session.get('name', '')}. Want to share more or try something to lift your spirits?"
                session['last_topic'] = 'sad'
            elif msg_sentiment == 'Positive':
                reply = f"That sounds so positive, {session.get('name', '')}! What’s making you feel this way?"
                session['last_topic'] = 'happy'
            else:
                reply = f"I’d love to hear more, {session.get('name', '')}. What’s on your mind?"
            next_state = 'engagement'

    elif current_state == 'suggestion':
        # Get recommendations based on the last detected mood
        recs = recommendations.get(session['last_topic'], {})
        activity = random.choice(recs.get('activities', ["a calming activity"]))
        playlist = random.choice(recs.get('playlists', ["a relaxing playlist"]))
        song = random.choice(recs.get('songs', ["a soothing song"]))

        if contains_keywords(user_msg, ['yes', 'sure', 'okay', 'let’s', 'yeah']):
            # Randomly choose between suggesting an activity, playlist, or song (or a combination)
            suggestion_type = random.choice(['activity', 'music', 'both'])
            
            if suggestion_type == 'activity':
                reply = f"Great, {session.get('name', '')}! Let’s try {activity}"
            elif suggestion_type == 'music':
                if random.choice([True, False]):  # Randomly choose between playlist or song
                    reply = f"How about listening to {playlist}, {session.get('name', '')}? It might help!"
                else:
                    reply = f"How about a song, {session.get('name', '')}? I recommend {song}."
            else:
                reply = f"Let’s try {activity} Or maybe you’d like to listen to {song} to help you feel better?"
            
            next_state = 'engagement'
        elif contains_keywords(user_msg, ['no', 'not really', 'nah']):
            reply = f"No worries, {session.get('name', '')}. Is there something else you’d like to talk about or do instead?"
            next_state = 'emotional_checkin'
        elif contains_keywords(user_msg, ['activity', 'activities']):
            reply = f"Sure, {session.get('name', '')}! Let’s try {activity}"
            next_state = 'engagement'
        elif contains_keywords(user_msg, ['music', 'song', 'songs', 'playlist']):
            if random.choice([True, False]):  # Randomly choose between playlist or song
                reply = f"How about listening to {playlist}, {session.get('name', '')}? It might help!"
            else:
                reply = f"How about a song, {session.get('name', '')}? I recommend {song}."
            next_state = 'engagement'
        else:
            reply = f"I’m here to help, {session.get('name', '')}. Would you like to try a different activity, listen to some music, or talk more about how you’re feeling?"
            next_state = 'suggestion'

    elif current_state == 'engagement':
        if contains_keywords(user_msg, activity_requests):
            # Offer a recommendation when the user explicitly asks for a suggestion
            recs = recommendations.get(session['last_topic'], {})
            activity = random.choice(recs.get('activities', ["a calming activity"]))
            playlist = random.choice(recs.get('playlists', ["a relaxing playlist"]))
            reply = f"Sure thing, {session.get('name', '')}! How about {activity} Or maybe you’d enjoy {playlist}?"
            next_state = 'suggestion'
        elif contains_keywords(user_msg, farewells):
            reply = f"Take care, {session.get('name', '')}! I’ll be here whenever you need me. 🌟"
            next_state = 'farewell'
        else:
            # Check if user hasn’t journaled recently
            if recent_journal:
                last_journal_date = recent_journal.date
                days_since_journal = (date.today() - last_journal_date).days
                if days_since_journal > 3:
                    reply = f"It’s been a while since you last journaled, {session.get('name', '')}. Want to write about what’s been going on?"
                    next_state = 'suggestion'
                else:
                    reply = f"Thanks for sharing, {session.get('name', '')}. How can I support you right now?"
                    next_state = 'emotional_checkin'
            else:
                reply = f"You haven’t journaled recently—maybe it’s time to jot down your thoughts?"
                next_state = 'suggestion'

    elif current_state == 'farewell':
        reply = f"See you soon, {session.get('name', '')}! I’m always here if you need to chat. 🌟"
        next_state = 'greeting'  # Reset to greeting for next interaction

    # Update conversation state
    session['conversation_state'] = next_state

    return jsonify({'reply': reply})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)