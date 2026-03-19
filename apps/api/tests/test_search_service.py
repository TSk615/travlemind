from travelmind_api.services.search_service import search_documents



def test_search_documents_include_structured_fields_for_seed_and_manual_links():
    results = search_documents(
        query="quiet coffee",
        destination="Kyoto",
        manual_links=["https://example.com/custom-guide"],
    )

    assert len(results) >= 2

    seed_document = next(item for item in results if item.platform == "official-tourism")
    assert seed_document.place_name
    assert seed_document.category
    assert seed_document.opening_hours
    assert seed_document.price_hint
    assert seed_document.address
    assert seed_document.geo is not None
    assert seed_document.source_type.startswith("official")

    manual_document = next(item for item in results if item.platform == "manual-link")
    assert manual_document.place_name == "Custom Guide"
    assert manual_document.category == "external-reference"
    assert manual_document.opening_hours == "Check source page"
    assert manual_document.price_hint == "See source page"
    assert manual_document.address == "example.com"
    assert manual_document.geo is None
    assert manual_document.source_type == "manual-link"
    assert all(item.scores.final_score > 0 for item in results)



def test_search_documents_skip_invalid_and_duplicate_manual_links():
    results = search_documents(
        query="quiet coffee",
        destination="Kyoto",
        manual_links=[
            " https://example.com/custom-guide ",
            "https://example.com/custom-guide/",
            "ftp://example.com/unsupported",
            "not-a-url",
            "   ",
        ],
    )

    manual_links = [item for item in results if item.platform == "manual-link"]
    assert len(manual_links) == 1
    assert manual_links[0].url == "https://example.com/custom-guide"



def test_search_documents_respect_destination_filter_for_seed_data():
    results = search_documents(
        query="temple",
        destination="Kyoto",
        manual_links=[],
    )

    assert results
    assert all(item.destination == "Kyoto" for item in results)
    assert all(item.place_name for item in results)
    assert not any(item.destination == "Tokyo" for item in results)



def test_search_documents_query_matches_structured_fields():
    results = search_documents(
        query="Yabunouchicho",
        destination=None,
        manual_links=[],
    )

    assert any(item.place_name == "Fushimi Inari Taisha" for item in results)
