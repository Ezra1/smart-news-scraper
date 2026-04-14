from src.incident_filter import is_incident_article, should_skip_llm


class TestIncidentFilter:
    def test_seizure_article_is_incident(self):
        text = "Police seized 500 boxes of counterfeit semaglutide at the border"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is True
        assert has_enf is True
        assert has_ph is True

    def test_commentary_not_incident(self):
        text = "Experts discuss rising trends in pharmaceutical crime globally"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is False
        assert has_ph is True
        assert has_enf is False

    def test_non_pharma_skipped(self):
        text = "Tech company reports data breach affecting millions"
        skip, score = should_skip_llm("Data breach", text)
        assert skip is True
        assert score == 0.0

    def test_incident_sent_to_llm(self):
        text = "Customs officials seized unauthorized injectable peptides"
        skip, score = should_skip_llm("Seizure", text)
        assert skip is False
        assert score is None

    def test_pharma_no_incident_low_score(self):
        text = "The pharmaceutical industry faces new challenges"
        skip, score = should_skip_llm("Industry news", text)
        assert skip is True
        assert score == 0.3

    def test_non_english_query_language_does_not_skip_llm(self):
        text = "这篇文章讨论了药品监管和查处行动"
        skip, score = should_skip_llm("伪劣药品", text, query_language="zh")
        assert skip is False
        assert score is None

    def test_non_ascii_dominant_text_does_not_skip_llm(self):
        text = "药品 伪劣 药物 执法 行动 调查 部门 公告"
        skip, score = should_skip_llm("伪劣药品", text)
        assert skip is False
        assert score is None

    def test_weak_enforcement_without_crime_not_incident(self):
        text = "Police discuss pharmaceutical policy trends for 2026"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is False
        assert has_enf is False
        assert has_ph is True

    def test_weak_enforcement_with_crime_is_incident(self):
        text = "Customs investigation uncovered illicit medicines at the border"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is True
        assert has_enf is True
        assert has_ph is True

    def test_commentary_terms_do_not_override_strong_event(self):
        text = "Analysis: Police seized counterfeit insulin vials in a warehouse raid"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is True
        assert has_enf is True
        assert has_ph is True

    def test_word_boundary_avoids_partial_term_false_positive(self):
        text = "Police seized cocaine at the border checkpoint"
        is_inc, has_enf, has_ph = is_incident_article(text)
        assert is_inc is False
        assert has_enf is True
        assert has_ph is False

    def test_theft_with_investigation_sent_to_llm(self):
        text = "Customs investigation into theft of prescription diabetes medications"
        skip, score = should_skip_llm("probe", text)
        assert skip is False
        assert score is None

