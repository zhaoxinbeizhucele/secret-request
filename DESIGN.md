---
name: Secret Request
description: 本人确认用途并输入一次机密的简单表单
colors:
  bg: "#f6f6f8"
  card: "#ffffff"
  inset: "#f8f8fa"
  text: "#16161a"
  muted: "#696d78"
  line: "rgba(15,15,25,.09)"
  accent: "#5b5bd6"
  on-accent: "#ffffff"
  error: "#c4302b"
  dark-bg: "#08090a"
  dark-card: "#111214"
  dark-inset: "#0b0c0e"
  dark-text: "#f4f5f7"
  dark-muted: "#8d929c"
  dark-line: "rgba(255,255,255,.08)"
  dark-accent: "#8b8cf8"
  dark-on-accent: "#0b0b1a"
  dark-error: "#ff8a80"
typography:
  title:
    fontFamily: 'Inter, "SF Pro Text", system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif'
    fontSize: "19px"
    fontWeight: 650
    lineHeight: 1.35
    letterSpacing: "-0.018em"
  body:
    fontFamily: 'Inter, "SF Pro Text", system-ui, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif'
    fontSize: "15px"
    lineHeight: 1.6
  code:
    fontFamily: '"SF Mono", ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace'
rounded:
  field: "8px"
  inset: "10px"
  card: "14px"
spacing:
  gap: "10px"
  field-gap: "18px"
  card-padding: "36px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.field}"
    padding: "11px 16px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "10px 12px"
    focusRing: "3px {colors.accent} @ 28%"
---

# Design System: Secret Request

## Overview

输入页是一张居中的“认证卡片”式表单（参考 Clerk 的清爽卡片与表单），首页是偏暗的产品页（参考 Linear 的近黑底、发丝线和克制强调色）。两页共用冷灰中性色、同一靛紫强调色、同一系统字体栈，并随系统切换浅色/深色。只使用系统字体和本地资源；不加载外部字体、图片或脚本，CSP 不变。输入页优先让本人确认正在给谁提供什么：标题、自行声明的申请 Agent、申请时间、用途、剩余时间、一个或多个带标签的输入区及提交/拒绝。

## Colors

冷灰中性色：浅色为 #f6f6f8 背景、白色卡片；深色为 #08090a 近黑背景、#111214 卡片。分隔一律用 1px 半透明发丝线。唯一强调色为靛紫（浅色 #5b5bd6、深色 #8b8cf8），只用于主按钮、剩余时间、焦点环、步骤编号和少量链接；首页主按钮用反色（深色模式白底黑字），不用彩色 CTA。错误使用独立红色，带浅底和细边框。仅在页面顶部边缘使用很淡的径向光晕。

## Typography

Inter 优先（仅当本机已安装），回退到 SF Pro / system-ui / 苹方 / 微软雅黑 / Noto Sans CJK。标题字重 600–650、负字距（输入页 -0.018em，首页大标题 -0.035em）；正文 15px / 1.6；标签 13.5px、550 字重；辅助文字 12.5px 的弱灰色。命令、URL 与示例终端用等宽字体。

## Layout

输入卡片最大 440px，居中，内边距 36px；顶部为品牌标记，标题与状态居中。申请详情放在内嵌的浅色信息面板里，行间以发丝线分隔。520px 以下卡片内边距 28px 20px，提交在上、拒绝在下纵向排列，全宽。说明文字“由你选择并提供机密…”放在卡片下方，带小锁图标。

## Elevation & Depth

卡片使用 1px 边线加多层极柔和阴影（浅色）或发丝线加内高光（深色）。输入框浅色模式有 1px 阴影；聚焦时边框变为强调色并加 3px 半透明焦点环。不使用装饰动画；过渡仅 0.15s 颜色/阴影，并遵从减少动态效果。

## Shapes

卡片 14px（窄屏 12px），信息面板 10px，输入与按钮 8px。密码“显示/隐藏”按钮内嵌在输入框右侧。键盘焦点为 2px 卡片色间隔 + 2px 强调色描边。

## Components

按钮最小高度 44px，禁用时透明度 .55。主按钮带极轻的上亮下实渐变和内高光；次按钮为卡片色加 1px 边线。密码字段默认隐藏；多行文本明确提示明文显示，选填字段明确标注。错误使用 alert，提交/拒绝显示各自的忙碌文案；请求结束时隐藏输入区，结束提示显示在内嵌面板中。提交确认后尝试关闭输入页，浏览器禁止时显示关闭提示。Windows 与 macOS 只用按需通知打开输入页；webhook 同样指向该页。

只展示本次申请。请求结束后隐藏输入；断网明确表示提交尚未确认。Agent 名称由申请方声明，不代表经过身份认证；匿名服务没有已登记设备身份。

## Do's and Don'ts

- 保持申请 Agent、用途和操作标签完整可读，保留明显焦点与键盘操作。
- 终态应明确显示已交付、拒绝或过期，避免继续显示可输入表单。
- 不在通知、错误信息或截图中放入真实机密，不添加外部字体、分析或远程图片。
- 不使用大面积彩色渐变、蓝色 CTA 对、箭头流程图卡片或 emoji。

## 主题切换

两页共用“亮色 / 暗色 / 跟随系统”三段切换（默认跟随系统），以 `<html data-theme="light|dark">` 覆盖系统偏好；选“跟随系统”时移除该属性，由 `prefers-color-scheme` 实时决定。选择保存在 `localStorage` 的 `secret-request-theme`（两页共用；存储不可用时仅对当前页生效）。

- 颜色只定义一次：每个变量写成 `var(--light, 亮色值) var(--dark, 暗色值)`，由 `--light/--dark` 开关在系统偏好与 `data-theme` 之间切换，避免媒体查询与属性选择器两份色值漂移。
- 防闪烁：CSP 只允许同源脚本，因此用同步的外部脚本 `/assets/theme.js`（放在 `<head>`、样式表之前，不加 defer/async）在首帧前设置 `data-theme`。CSP 不变；该文件已加入服务端静态白名单、`build_skill.py` 与发布清单。
- 控件：`role="radiogroup"`（aria-label“界面主题”），三个 `role="radio"` 图标按钮（太阳/月亮/显示器内联 SVG，aria-label 与 title 为中文），方向键/Home/End 切换，仅选中项可 Tab 聚焦，焦点环为强调色。未选中图标用弱灰（≥4.5:1），选中项为卡片底 + 细边线。首页放在顶部导航右侧（窄屏在品牌行右上），填写页放在卡片右上角。脚本不可用时控件隐藏，页面仍跟随系统。

## 官网首页 /

首页与输入页共享色板、字体与焦点样式，默认按系统主题显示，深色为主视觉。它是产品介绍与安装入口，不承载输入表单。旧填写链接打开 /input/{id}；短链接打开 /i，凭据只放在 URL 片段里。首页片段若本身是一次填写凭据，则转到 /i。顺序：居中的简短介绍（胶囊标签、单行标题、弱灰引导段、反色主按钮 + 描边次按钮）；标注为“示例”的窗口框，左侧 Agent 终端片段、右侧缩略输入卡片；三步交付（发丝线分格）；安装命令与复制按钮；三种接入方式卡片；信任边界定义列表。桌面最大宽度 1080px，860px 以下单列，620px 以下收紧间距。顶部导航吸顶、半透明模糊背景。

首页标题 38–64px，移动端 36px；章节标题 26–34px，移动端 25px；引导正文 17px；正文 14.5–15px，说明 12–13px。

安装命令提供复制按钮及成功/剪贴板失败的状态反馈，错误时支持手动选中。公共服务、本机快速启动和自建 HTTPS 服务并列说明；本机链接不能手机填写的边界在页面明确列出。支持键盘跳转正文、导航锚点、减少动态效果和系统深色模式。
