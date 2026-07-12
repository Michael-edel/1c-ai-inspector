from app.services.patch_impact import analyze_patch_impact, enrich_patch_impact


def test_patch_impact_identifies_changed_1c_objects() -> None:
    impacts = analyze_patch_impact(
        [
            {"path": "Documents/SalesOrder/Forms/ObjectForm/Ext/Form/Module.bsl"},
            {"path": "CommonModules/Orders.bsl"},
        ]
    )
    assert {
        (item["objectFqn"], item["relation"])
        for item in impacts
    } == {
        ("Document.SalesOrder", "forms"),
        ("CommonModule.Orders", "object_module"),
    }
    assert all(item["risk"] == "candidate" for item in impacts)


def test_patch_impact_marks_matching_read_only_evidence() -> None:
    impacts = analyze_patch_impact([{"path": "Documents/SalesOrder/Module.bsl"}])

    enriched = enrich_patch_impact(
        impacts,
        [
            {
                "objectFqn": "Document.SalesOrder",
                "relation": "object_module",
                "sourceTool": "search_code",
                "evidence": ["CommonModule.Orders.CheckOrder at line 12"],
            }
        ],
    )

    assert enriched[0]["risk"] == "evidenced"
    assert enriched[0]["source"] == "search_code"
    assert enriched[0]["evidence"] == ["CommonModule.Orders.CheckOrder at line 12"]
