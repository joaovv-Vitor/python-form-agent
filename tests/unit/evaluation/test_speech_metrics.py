import pytest

from form_agent.evaluation.speech_metrics import real_time_factor, score_transcript


@pytest.mark.parametrize(
    "reference,hypothesis,edits,wer",
    [
        ("um dois três", "um quatro três", 1, 1 / 3),
        ("um dois três", "um três", 1, 1 / 3),
        ("um", "um dois três", 2, 2.0),
        ("João", "", 1, 1.0),
        ("", "alucinação", 1, None),
        ("", "", 0, None),
        ("Meu estado é Ceará.", "Meu estado é Ceara.", 1, 0.25),
        (" A  B ", "a b", 0, 0.0),
        ("Ceará", "Ceara\u0301", 0, 0.0),
    ],
)
def test_word_error_rate(reference, hypothesis, edits, wer):
    score = score_transcript(reference, hypothesis)
    assert score.word_edits == edits
    assert score.wer == wer


def test_character_error_and_rtf():
    assert score_transcript("Ceará", "Ceara").cer == 0.2
    assert real_time_factor(2, 10) == 0.2
    assert real_time_factor(2, 0) is None
    assert real_time_factor(2, None) is None
