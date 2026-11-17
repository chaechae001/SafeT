"""Cloud 업로드용 축소본과 프롬프트·대응표 묶음을 만든다(원본 사진은 읽기만).

실행(작업 폴더 루트에서): python 261116_기기탐지_YOLO전환_DR/scripts/prepare_cloud_inputs.py <출력_zip_경로>
- 사진: EXIF 회전 적용, 긴 변 1600px 이하로 축소, JPEG 품질 92, 파일명 = image_id + '.jpg'
- 묶음: images/*.jpg, class_map.json(대응표 행), manifest.json(원본·축소본 sha256)
축소본 zip은 산출물 폴더에 두지 않는다(원본 파생 이미지 복제 최소화). manifest는 산출물 폴더 cloud/에 남긴다.
"""
import hashlib
import io
import json
import os
import sys
import zipfile

from PIL import Image, ImageOps

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
OUT = os.path.join(ROOT, '261116_기기탐지_YOLO전환_DR')
MAXS = 1600


def main(zip_path):
    ev = json.load(open(os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR', '261115_기기인식_평가셋_v1_DR.json'), encoding='utf-8'))
    cmap = json.load(open(os.path.join(OUT, '261116_사전학습클래스_대응표_v1_DR.json'), encoding='utf-8'))
    manifest = []
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as z:
        for img in ev['images']:
            src = os.path.join(ROOT, img['file'])
            raw = open(src, 'rb').read()
            assert hashlib.sha256(raw).hexdigest() == img['sha256']
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
            im.thumbnail((MAXS, MAXS))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=92)
            b = buf.getvalue()
            z.writestr(f"images/{img['image_id']}.jpg", b)
            manifest.append({'image_id': img['image_id'], 'source_file': img['file'], 'source_sha256': img['sha256'],
                             'upload_file': f"images/{img['image_id']}.jpg", 'upload_sha256': hashlib.sha256(b).hexdigest(),
                             'width': im.size[0], 'height': im.size[1]})
        z.writestr('class_map.json', json.dumps(cmap['rows'], ensure_ascii=False, indent=1))
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1))
    os.makedirs(os.path.join(OUT, 'cloud'), exist_ok=True)
    json.dump({'resize_rule': f'EXIF 회전 적용, 긴 변 {MAXS}px 이하, JPEG q92', 'images': manifest},
              open(os.path.join(OUT, 'cloud', 'upload_manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(len(manifest), os.path.getsize(zip_path), hashlib.sha256(open(zip_path, 'rb').read()).hexdigest())


if __name__ == '__main__':
    main(sys.argv[1])
