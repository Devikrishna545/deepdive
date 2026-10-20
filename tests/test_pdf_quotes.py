"""PDF typesetting must not make true quotes fail the quote guard (live run, word2vec paper:
the authors and 6 other verified claims were removed because of "ﬁ", "repre-\\nsentations",
"in , with" and a title page that lists each author with an affiliation)."""

from __future__ import annotations

from app.core.guards import quote_in_sources
from app.core.utils import clean_document_text

TITLE_PAGE = ("Efﬁcient Estimation of Word Representations in\nVector Space\nTomas Mikolov\n"
              "Google Inc., Mountain View, CA\ntmikolov@google.com\nKai Chen\nGoogle Inc., Mountain View, CA\n"
              "kaichen@google.com\nGreg Corrado\nGoogle Inc., Mountain View, CA\ngcorrado@google.com\n"
              "Jeffrey Dean\nGoogle Inc., Mountain View, CA\njeff@google.com\nAbstract\nWe propose two novel "
              "model architectures for computing continuous vector repre-\nsentations of words from very large data sets.")
BODY = ("as far as we know, these\narchitectures were signiﬁcantly more computationally expensive for training "
        "than the one proposed\nin , with the exception of certain version of log-bilinear model")


def test_typeset_text_matches_the_plain_quote():
    assert quote_in_sources("We propose two novel model architectures for computing continuous vector "
                            "representations of words from very large data sets.", [TITLE_PAGE])
    assert quote_in_sources("these architectures were significantly more computationally expensive for "
                            "training than the one proposed in, with the exception", [BODY])
    assert quote_in_sources("a state-of-the-art model", ["we use a state-of-the-\nart model here"])


def test_author_list_quote_passes_only_with_the_real_names_in_order():
    assert quote_in_sources("Tomas Mikolov, Kai Chen, Greg Corrado, Jeffrey Dean", [TITLE_PAGE])
    assert not quote_in_sources("Tomas Mikolov, Yoshua Bengio, Greg Corrado", [TITLE_PAGE])  # invented name
    assert not quote_in_sources("Jeffrey Dean, Tomas Mikolov", [TITLE_PAGE])  # wrong order
    assert not quote_in_sources("Kai, Greg, Dean", [TITLE_PAGE])  # crumbs only
    assert not quote_in_sources("Tomas Mikolov, Kai Chen", [BODY])  # not in this passage


def test_clean_document_text():
    assert clean_document_text("signiﬁcantly") == "significantly"
    assert clean_document_text("vector repre-\nsentations") == "vector representations"
    assert clean_document_text("state-of-the-\nart") == "state-of-the-\nart"  # compound keeps its hyphen
    assert clean_document_text("proposed in , with") == "proposed in, with"
    assert clean_document_text("Line one\nLine two") == "Line one\nLine two"  # line breaks kept


def test_hyphen_left_inside_a_word_still_matches_but_other_words_do_not():
    assert quote_in_sources("selects the best one using various quality metrics", ["selects the best one using various qual-ity metrics"])
    assert not quote_in_sources("selects the worst one using various quality metrics", ["selects the best one using various qual-ity metrics"])
