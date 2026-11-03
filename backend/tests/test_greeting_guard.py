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
