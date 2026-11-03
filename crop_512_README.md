# 512×512 图像与语义标签裁剪

`crop_512.py` 是本次整理的新脚本，默认边界规则参考项目已有的 `server_training_isaid/scripts/reconstruct_isaid_tiles.py`。它没有经过原始实验数据逐项比对，不能仅凭裁剪尺寸相同就称为历史实验的原始预处理代码。

## 使用

依赖：Python 3、Pillow、NumPy。安装依赖：

```bash
pip install Pillow numpy
```

输入目录分别存图像和标签；允许 PNG/JPEG/TIFF/BMP，非递归读取。图像与标签按不含扩展名的文件名配对，例如 `area1.tif` 对应 `area1.png`。标签与图像尺寸必须相同。

```bash
python scripts/crop_512.py --images data/raw/train/images --masks data/raw/train/masks --output data/train_512
python scripts/crop_512.py --images data/raw/test/images --masks data/raw/test/masks --output data/test_512
```

路径有空格时加引号。先替换为你自己的原图、标签和输出目录。输出必须是新目录或空目录，已有文件不会被覆盖。无标签图像可以省略 `--masks`。

若标签文件名额外带后缀，例如图像 `P0001.png`、标签 `P0001_instance_color_RGB.png`，添加：

```bash
python scripts/crop_512.py --images data/raw/images --masks data/raw/labels --mask-suffix _instance_color_RGB --palette data/palette.txt --output data/train_512
```

### 标签编码

- 单通道或调色板索引标签：保留原类别编号，要求像素值为 0–255 的整数，不进行重映射。需要自行确认调色板索引就是训练使用的类别 ID。
- RGB 彩色标签：必须通过 `--palette` 提供真实的颜色与类别编号映射。映射文件每行采用 `类别编号: R,G,B` 格式，例如 `0: 0,0,0`。这只是格式示例，不代表任一数据集的实际映射。
- 映射里没有的颜色会报错，不会默认为背景。默认补齐标签为 255，可用 `--ignore-index` 修改；不把背景 0 当作忽略类。
- 输入图像转为三通道 RGB；不适用于需要保留多光谱波段、地理坐标或高位深数据的任务。输出 PNG 不包含原始 GeoTIFF 地理信息。

## 裁剪规则

- 固定 512×512，步长 512，不缩放、不插值、不增强，不筛除背景块。
- 末端不足 512 时，最后一个窗口向内移动并贴齐原图边界，因此末端可能有重叠。
- 原图某一边小于 512 时，该边右侧或下侧补齐：图像填 0，标签填忽略值（默认 255）。
- 图像和标签使用同一窗口；名称含原图名和左上角坐标，例如 `area1_y00000_x00512_orig.png`。
- 按文件名、纵坐标、横坐标固定顺序输出，不含随机操作。

输出：

```text
train_512/
  images/          # 512×512 RGB 图像
  masks/           # 512×512 单通道类别标签（有输入标签时生成）
  samples.txt      # 每行一个裁剪块文件名，与当前项目 images/、masks/ 读取方式兼容
  tiles.jsonl      # 每块对应的原图、坐标、有效区域与原始尺寸
  preprocess.json # 裁剪参数、标签映射及输出数量；成功完成后才生成
```

运行中出错时输出目录可能包含部分结果；请检查错误后更换新的输出目录，勿将未完成结果直接用于训练。

## 与论文复现的关系

先按实际实验的原始场景/大图划分确定训练、验证、测试集合，再分别裁剪，避免同一大图相邻或重叠块跨训练与测试集合。不要把全部原图混在一起裁剪后随机生成测试集。

这个脚本只定义空间裁剪，**不会生成 1/4、1/8、1/16、1/32 的有标注/无标注划分**。公开时还应提供实验实际使用的 `label.txt`、`unlabel.txt`、验证/测试清单；若历史文件名与新脚本不同，需要提供明确对应关系，不能重新抽样后声称复现原实验。仅提供裁剪脚本，不能替代论文所称的“公开数据划分”。
