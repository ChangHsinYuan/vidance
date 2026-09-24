# Vidance 剪辑指令模式库（v10 时间线拼接）

> 用途：① 人手查命令/斜杠片段 ② 后续 SFT（指令→命令/时间线）的数据源。
> 每条 = `id` + `自然语言指令`（多样说法）+ `斜杠命令`（前端用）+ `CLI` + `时间线 JSON 片段` + `参数`。
> 生成方式：以现有时间线（`docs/example/compose_demo.json`、`output/tl_test.json`）为种子反向写成多样化中文指令。
> 测试素材（只用现成 clip，勿现场生成）：
> - `A = output/custom/clips/01A.mp4`
> - `B = output/custom/clips/01B.mp4`
> - `F = output/custom/final.mp4`

结构：
- `[CAT]` 类别：拼接 / 转场 / 裁剪 / 变速 / 特效 / 叠加 / 音频 / 组合
- `id`：`fx-001` 递增
- `tl`：可直接塞进时间线的片段

---

## 一、拼接与转场

### fx-001 直接拼接两段（硬切）
- 自然语言：*把 A 和 B 首尾接起来，不要转场* / *A 接 B，硬切*
- 斜杠：`/compose A.mp4 B.mp4`
- CLI：`python core/vidance.py compose A.mp4 B.mp4 -o out.mp4`
- tl：`main: [{source:A}, {source:B}]`

### fx-002 淡入淡出转场拼接
- 自然语言：*A 和 B 拼一起，中间淡入淡出，过渡 0.5 秒* / *两段之间用 fade 过渡*
- 斜杠：`/compose A.mp4 B.mp4 --transition fade --transition-duration 0.5`
- CLI：`python core/vidance.py compose A.mp4 B.mp4 --transition fade --transition-duration 0.5 -o out.mp4`
- tl：`main: [{source:A}, {source:B, transition_in:{kind:"fade", duration:0.5}}]`

### fx-003 左滑转场拼接
- 自然语言：*A 和 B 用向左滑动的方式切换* / *slideleft 转场*
- CLI：`python core/vidance.py compose A.mp4 B.mp4 --transition slideleft --transition-duration 0.4 -o out.mp4`
- tl：`{source:B, transition_in:{kind:"slideleft", duration:0.4}}`

### fx-004 圆形展开转场
- 自然语言：*第二段用圆圈展开的方式出现* / *circleopen 过渡*
- tl：`{source:B, transition_in:{kind:"circleopen", duration:0.5}}`

### fx-005 擦除转场
- 自然语言：*A 到 B 用左擦除切换* / *wipeleft*
- tl：`{source:B, transition_in:{kind:"wipeleft", duration:0.5}}`

### fx-006 三段不同转场串联
- 自然语言：*A、B、F 三段串起来，第一段切第二段用滑动，第二段切第三段圆圈展开*
- tl：
```json
"main": [
  {"id":"c1","source":"A"},
  {"id":"c2","source":"B","transition_in":{"kind":"slideleft","duration":0.5}},
  {"id":"c3","source":"F","transition_in":{"kind":"circleopen","duration":0.5}}
]
```
- 可用转场 kind 全集见 `utils/effects.py:XFADE_KINDS`（fade/slideleft/slideright/slideup/slidedown/circleopen/circleclose/wipeleft/wiperight/wipeup/wipedown/pixelize/hblur/dissolve/radial/smoothleft/…30+）

---

## 二、裁剪

### fx-010 截取片段
- 自然语言：*只要 A 从第 2 秒到第 5 秒* / *裁剪 A 的 2-5 秒*
- tl：`{source:"A", trim_start:2.0, trim_end:5.0}`
- CLI：`python utils/compose.py run timeline.json`（裁剪写在 JSON）

### fx-011 固定展示时长
- 自然语言：*A 只放 3 秒*
- tl：`{source:"A", trim_start:0, duration:3.0}`

### fx-012 从某秒开始取默认长度
- 自然语言：*从 A 的第 1.5 秒开始，放 2.5 秒*
- tl：`{source:"A", trim_start:1.5, duration:2.5}`

---

## 三、变速与静音

### fx-020 加速
- 自然语言：*这段放快 1.5 倍* / *加速 1.5x*
- tl：`{source:"B", rate:1.5}`

### fx-021 慢放
- 自然语言：*慢放一半* / *0.5 倍速*
- tl：`{source:"B", rate:0.5}`

### fx-022 静音原声（配音用）
- 自然语言：*去掉这段的原声*
- tl：`{source:"B", volume:0}`

### fx-023 降低原声音量
- 自然语言：*原声调小一点，留 30%*
- tl：`{source:"B", volume:0.3}`

---

## 四、镜头内特效（8 种）

### fx-030 闪白开场
- 自然语言：*开头来个闪白* / *片头闪一下白光*
- tl：`effects:[{"name":"flash"}]`
- 变体：闪黑 `{"name":"flash","kind":"black"}`

### fx-031 快速推进强调
- 自然语言：*快速推近强调一下* / *punch in 效果*
- tl：`effects:[{"name":"punch_in","strength":1.3}]`

### fx-032 数字故障
- 自然语言：*加点glitch故障感* / *赛博故障噪点*
- tl：`effects:[{"name":"glitch"}]`

### fx-033 胶片颗粒+暗角
- 自然语言：*加胶片颗粒和暗角* / *电影质感做旧*
- tl：`effects:[{"name":"grain_vignette","grain":0.02}]`

### fx-034 甩镜平移
- 自然语言：*来个甩镜* / *镜头快速横移*
- tl：`effects:[{"name":"wipe","sweep":0.3}]`

### fx-035 整体推拉
- 自然语言：*缓缓推近* / *zoom in*
- tl：`effects:[{"name":"zoom","direction":"in"}]`
- 变体：拉远 `{"name":"zoom","direction":"out"}`

### fx-036 变速斜坡
- 自然语言：*前面正常，后面突然加速* / *速度斜坡*
- tl：`effects:[{"name":"speed_ramp","factor":1.5,"cut":0.7}]`

### fx-037 定格放大
- 自然语言：*结尾定格放大* / *末帧停住并放大*
- tl：`effects:[{"name":"freeze_zoom","hold":0.5,"strength":1.3}]`

### fx-038 特效叠加（多特效链）
- 自然语言：*先闪白再推近* / *胶片颗粒加推拉*
- tl：`effects:[{"name":"flash"},{"name":"punch_in","strength":1.3}]`

---

## 五、叠加（画中画 / 文字）

### fx-040 右下角画中画
- 自然语言：*右下角放个小窗口播放 F* / *画中画，右下角，占 30% 宽*
- tl：
```json
{"overlay":[{"type":"video","source":"F","start":2.0,"duration":3.0,
  "scale":0.28,"pos":{"x":"W-w-30","y":"H-h-30"},"opacity":0.9}]}
```

### fx-041 左上角画中画
- 自然语言：*左上角叠个小视频*
- tl：`"pos":{"x":"30","y":"30"}`

### fx-042 居中标题文字
- 自然语言：*中间加个大标题"我的视频"* / *居中打标题*
- tl：
```json
{"overlay":[{"type":"text","text":"我的视频","start":0.5,"duration":3,
  "fontsize":56,"fontcolor":"white","pos":{"x":"(W-tw)/2","y":"80"}}]}
```

### fx-043 左下角说明文字
- 自然语言：*左下角写一行字"拍摄于2026"*
- tl：`{"pos":{"x":"40","y":"H-th-60"},"fontcolor":"white"}`

### fx-044 右上角水印（全程）
- 自然语言：*全程右上角水印 @我的账号*
- tl：
```json
{"overlay":[{"type":"text","text":"@我的账号","start":0,"duration":9999,
  "fontsize":28,"fontcolor":"white","pos":{"x":"W-tw-30","y":"30"}}]}
```

### fx-045 多文字层（不同位置颜色）
- 自然语言：*开头黄字标题，3秒后左边红字"GLITCH"，6秒后底部白字说明*
- tl：见 `docs/example/compose_demo.json` 的 overlay 段

---

## 六、音频

### fx-050 加 BGM
- 自然语言：*配上背景音乐* / *加个轻柔的配乐*
- tl：`audio:[{"source":"bgm/calm.wav","start":0,"volume":0.3}]`

### fx-051 BGM 自动闪避
- 自然语言：*配乐在有旁白时自动压低* / *BGM 闪避人声*
- tl：`audio:[{"source":"bgm/calm.wav","start":0,"volume":0.3,"ducking":true}]`

### fx-052 BGM 延迟进入
- 自然语言：*3秒后再进音乐*
- tl：`audio:[{"source":"bgm/calm.wav","start":3.0,"volume":0.3,"ducking":true}]`

### fx-053 多音轨混音
- 自然语言：*一路旁白一路配乐混一起*
- tl：`audio:[{source:"voice.wav",volume:1.0},{source:"bgm/calm.wav",volume:0.25,ducking:true}]`

---

## 七、组合（复杂指令）

### fx-060 营销号片头
- 自然语言：*开头闪白，接标题文字，配乐小声，画面推近*
- tl：
```json
{
  "main":[{"id":"c1","source":"A","trim_start":0,"duration":3,
    "effects":[{"name":"flash"},{"name":"zoom","direction":"in"}]}],
  "overlay":[{"type":"text","text":"标题","start":0.3,"duration":2.5,
    "fontsize":56,"fontcolor":"yellow"}],
  "audio":[{"source":"bgm/uplifting.wav","start":0,"volume":0.3,"ducking":true}]
}
```

### fx-061 特效混剪
- 自然语言：*A 闪白推近、B 故障感、F 胶片颗粒加推拉，段间用不同转场，右下角画中画，配乐闪避*
- tl：完整见 `docs/example/compose_demo.json`（本条即该样本）

### fx-062 素材加片尾水印
- 自然语言：*给 F 全程加右下角水印，配轻音乐*
- tl：见 `docs/example/compose_demo.json` 的 overlay+audio 结构

### fx-063 多段变速卡点
- 自然语言：*A 正常、B 加速 2 倍、F 慢放 0.5 倍，硬切*
- tl：
```json
"main":[
  {"source":"A"},
  {"source":"B","rate":2.0},
  {"source":"F","rate":0.5}
]
```

---

## 附：时间线 JSON 字段速查

见 [usage-v10.md](../usage-v10.md) 的「时间线 JSON 格式」与「效果总表」。

## 附：生成方式说明

本库由现有时间线样本（`docs/example/compose_demo.json`、`output/tl_test.json`）经反向改写扩增得到；每条的自然语言指令保留多种口语说法，作为 SFT 的 instruction 侧，`tl` / CLI / 斜杠命令为 output 侧。
