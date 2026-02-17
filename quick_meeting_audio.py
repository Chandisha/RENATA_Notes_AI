# quick_meeting_audio.py
from gtts import gTTS
import os

meeting_text = """
Good morning everyone. This is our quarterly review meeting for Q4 2024.
Let me start with the sales update. John, our sales have increased by 15 percent this quarter.
That's excellent news. Sarah, can you share the marketing metrics?
Sure. We had 50,000 new users sign up last month. Our social media engagement is up by 30 percent.
Great work team. Now let's discuss action items.
John, please prepare the client presentation by next Friday.
Sarah, schedule a follow-up meeting with the design team for next week.
Does anyone have questions? No? Okay, meeting adjourned. Thank you everyone.
"""

tts = gTTS(meeting_text, lang='en')
tts.save("test_meeting.mp3")
print("✅ Created test_meeting.mp3")