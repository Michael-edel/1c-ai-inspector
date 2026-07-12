from app.services.patch_impact import analyze_patch_impact


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
