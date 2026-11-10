"""验证论文图件格式、空输入门槛和清单。
作者：Codex。版本：v0.1.0。运行：python -m pytest tests/scr_check_figures.py。
输入：合成冻结表。输出：pytest 临时目录中的矢量图和 PNG。
"""
from struct import unpack

from src.M10.scr_plot_figures import export_figures


def figure_inputs():
    """构造覆盖接续类别、缺失窗口和跨产品匹配的图件输入。"""
    event = dict(route1_A_eligible=True)
    events = [dict(event, RT=i % 12 + 1, delta_SMP=8+i % 24, RR=(8+i % 24)/(i % 12+1),
                   F_R=i % 5 < 3 if i % 5 < 4 else None,
                   F_R_subtype=("pre", "sync", "post")[i % 3] if i % 5 < 3 else None,
                   Lag_FR=i % 12 if i % 5 < 3 else None)
              for i in range(1, 201)]
    flow = [dict(step_order=i, n_before=a, n_after=b, n_excluded=a-b)
            for i, (a, b) in enumerate(((420, 310), (310, 246), (246, 200), (200, 160)), 1)]
    agreement = [
        dict(product_combo=combo, main_hit=a, alt_hit=b, jaccard=j)
        for combo, a, b, j in [("era5land__chirps20", .78, .82, .67), ("gldas21__gldas21", .62, .72, .50)]
    ]
    return dict(event_master=events, sample_flow=flow, cross_product_match_summary=agreement)


def test_publication_exports(tmp_path):
    """确认真实格式、页面尺寸和矢量文本，缺项不产生占位图。"""
    manifest = export_figures(tmp_path, figure_inputs(), {"run_id": "synthetic"})
    exported = [row for row in manifest if row["status"] == "exported"]
    assert [row["figure"][:5] for row in exported] == ["fig01", "fig02", "fig03", "fig05"]
    assert len(list(tmp_path.iterdir())) == 12
    for row in exported:
        name = row["figure"]
        assert (tmp_path / f"{name}.pdf").read_bytes().startswith(b"%PDF-")
        assert "<text" in (tmp_path / f"{name}.svg").read_text(encoding="utf-8")
        png = (tmp_path / f"{name}.png").read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        width, height = unpack(">II", png[16:24])
        assert abs(width - row["width_mm"] * 600 / 25.4) < 1.1
        assert abs(height - row["height_mm"] * 600 / 25.4) < 1.1


def test_empty_inputs_are_omitted(tmp_path):
    """空队列只记录缺项，不导出空白图。"""
    manifest = export_figures(tmp_path, dict(event_master=[], sample_flow=[],
                                             cross_product_match_summary=[]), {})
    assert all(row["status"] == "omitted" and row["reason"] for row in manifest)
    assert not list(tmp_path.iterdir())
