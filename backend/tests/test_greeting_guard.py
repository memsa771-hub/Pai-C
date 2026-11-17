"""A second greeting in the same conversation is dropped (R-47 C6)."""
import pytest

from app.pai_c.voice.guards import drop_repeat_greeting, leading_greeting

EARLIER = [{"role": "assistant", "content": "Assalam o alaikum Ayesha! Main PAI hoon."}]


@pytest.mark.req("R-47")
def test_repeat_greeting_is_dropped_only_after_an_earlier_greeting():
    assert drop_repeat_greeting("Wa alaikum assalam, Ayesha! MBBS ke liye marks batao.", EARLIER) == "MBBS ke liye marks batao."
    assert drop_repeat_greeting("Hello Ayesha. Let's look at BDS.", EARLIER) == "Let's look at BDS."
    assert drop_repeat_greeting("Wa alaikum assalam, Ayesha! MBBS ke liye marks batao.", []) == "Wa alaikum assalam, Ayesha! MBBS ke liye marks batao."
    assert drop_repeat_greeting("Wa alaikum assalam!", EARLIER) == "Wa alaikum assalam!"
    assert drop_repeat_greeting("MBBS is a good fit. Hello to your family too.", EARLIER) == "MBBS is a good fit. Hello to your family too."
    assert drop_repeat_greeting("Hi there! the high merit list is out.", [{"role": "assistant", "content": "Hi Ayesha!"}]) == "The high merit list is out."
    assert drop_repeat_greeting("Highlights first, then fees.", EARLIER) == "Highlights first, then fees."


@pytest.mark.req("R-47")
def test_leading_greeting_offsets():
    assert leading_greeting("Assalam o alaikum Ayesha! Main PAI hoon.") == len("Assalam o alaikum Ayesha!")
    assert leading_greeting("Hello Ayesha Khan Sahiba, welcome back. Next.") == 0
    assert leading_greeting("Hello Ayesha Khan. Next.") == len("Hello Ayesha Khan.")
    assert leading_greeting("Highlights first, then fees.") == 0
    assert leading_greeting("") == 0


@pytest.mark.req("R-47")
def test_user_greetings_do_not_count_as_an_earlier_greeting():
    history = [{"role": "user", "content": "Hello!"}, {"role": "assistant", "content": "Tell me about you."}]
    assert drop_repeat_greeting("Hello Ayesha. Let's look at BDS.", history) == "Hello Ayesha. Let's look at BDS."


@pytest.mark.req("R-47")
def test_greeting_sentence_ending_in_a_question_is_kept():
    assert drop_repeat_greeting("Hey, MBBS kyun? Batao.", EARLIER) == "Hey, MBBS kyun? Batao."
    assert drop_repeat_greeting("Hi, kaise ho? Batao.", EARLIER) == "Hi, kaise ho? Batao."
    assert drop_repeat_greeting("Salam Ayesha\u061f Batao.", EARLIER) == "Salam Ayesha\u061f Batao."


@pytest.mark.req("R-47")
def test_long_earlier_greeting_still_counts():
    long_earlier = [{"role": "assistant", "content": "Assalam o alaikum Ayesha, main PAI hoon aapki counsellor! Batao."}]
    assert leading_greeting(long_earlier[0]["content"]) == 0
    assert drop_repeat_greeting("Hello Ayesha. Let's look at BDS.", long_earlier) == "Let's look at BDS."
    assert drop_repeat_greeting("Hello Ayesha, welcome back to your counselling session. BDS next.", long_earlier) \
        == "Hello Ayesha, welcome back to your counselling session. BDS next."


@pytest.mark.req("R-47")
def test_students_salaam_is_returned_but_no_greeting_means_still_dropped():
    reply = "Wa alaikum assalam! Aaj kya baat karein?"
    assert drop_repeat_greeting(reply, EARLIER, student_text="Assalam o alaikum") == reply
    assert drop_repeat_greeting("Wa alaikum assalam! Aaj batao.", EARLIER, student_text="Assalam o alaikum, main Ayesha hoon, kaise hain aap") \
        == "Wa alaikum assalam! Aaj batao."
    assert drop_repeat_greeting("Wa alaikum assalam! Aaj batao.", EARLIER, student_text="MBBS ke baare mein batao") == "Aaj batao."
    assert drop_repeat_greeting("Wa alaikum assalam! Aaj batao.", EARLIER) == "Aaj batao."
