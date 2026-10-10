"""显式验收：只读已有帧，实际模型查询和Streamlit页面测试。"""
import json
import time

from search import HERE, SOURCE, JulyCatalog, DinoSearch, TextSearch, Image, read_json


def main():
    from streamlit.testing.v1 import AppTest
    catalog = JulyCatalog()
    image_engine = DinoSearch(catalog)
    samples = []
    # 仅三张已有JPEG，分布于首、中、末视频，不扫描或打开视频。
    video_ids = list(catalog.videos)
    for vid in (video_ids[0], video_ids[len(video_ids) // 2], video_ids[-1]):
        index_id = next(int(i) for i in catalog.ids
                        if catalog.rows[int(i)]['video_id'] == vid and catalog.rows[int(i)]['timestamp'] >= 120)
        expected = catalog.rows[index_id]
        with Image.open(catalog.image_path(expected)) as image:
            started = time.perf_counter()
            rows = image_engine.search(image)
        assert len(rows) == 10 and all(r['video_id'] in catalog.videos for r in rows)
        assert rows[0]['video_id'] == vid and abs(rows[0]['timestamp'] - expected['timestamp']) < .001, rows[0]
        assert rows[0]['similarity'] > .999
        samples.append(dict(query_index=index_id, top1=rows[0], seconds=time.perf_counter() - started))
    del image_engine
    text_engine = TextSearch(catalog)
    queries = []
    for text in ('陶老师给患者按摩腰部', '患者趴在床上治疗', '治疗肩颈的视频'):
        started = time.perf_counter()
        rows, prompt, notes = text_engine.search(text)
        assert len(rows) == 10 and all(r['video_id'] in catalog.videos for r in rows)
        assert all(rows[i]['similarity'] >= rows[i + 1]['similarity'] for i in range(9))
        assert all(__import__('pathlib').Path(r['image']).is_file() for r in rows)
        queries.append(dict(text=text, prompt=prompt, notes=notes, results=rows, seconds=time.perf_counter() - started))
    del text_engine
    app = AppTest.from_file(str(HERE / 'app.py'), default_timeout=90).run()
    assert not app.exception, app.exception
    next(button for button in app.button if button.label == '搜索相似画面').click().run()
    assert len(app.warning) == 1 and not app.exception
    app.radio(key='search_mode').set_value('文字搜索').run()
    app.text_input(key='query_text').set_value('治疗肩颈的视频')
    next(button for button in app.button if button.label == '搜索相关画面').click().run(timeout=90)
    assert not app.exception and not app.error, (app.exception, app.error)
    assert len(app.session_state['search_result']['rows']) == 10
    assert len(app.image) == 10, len(app.image)
    app.text_input(key='query_text').set_value('患者开飞机')
    next(button for button in app.button if button.label == '搜索相关画面').click().run()
    assert len(app.error) == 1 and 'search_result' not in app.session_state
    states = read_json(HERE / 'protected_before.json')
    from pathlib import Path
    root = HERE.parents[2]
    unchanged = all({'size': (root / path).stat().st_size, 'mtime_ns': (root / path).stat().st_mtime_ns} == state
                    for path, state in states.items())
    assert unchanged, '受保护文件状态发生变化'
    output = dict(july_videos=len(catalog.videos), july_frames=len(catalog.ids),
                  image_tests=samples, text_tests=queries, app_test='passed',
                  protected_files_unchanged=unchanged,
                  text_relevance='仅验证真实编码、排序、范围和展示；未做人工标注准确率评测')
    (HERE / 'validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('VALIDATION PASSED', flush=True)


if __name__ == '__main__':
    main()
