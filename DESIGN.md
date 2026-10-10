---
name: Secret Request
description: 本人确认用途并输入一次机密的简单表单
colors:
  bg: "#f4f6f8"
  surface: "#ffffff"
  text: "#18212c"
  muted: "#526170"
  line: "#c4cdd6"
  accent: "#165ac6"
  on-accent: "#ffffff"
  error: "#a42622"
  dark-bg: "#151a20"
  dark-surface: "#202730"
  dark-text: "#eef2f6"
  dark-muted: "#b7c3d0"
  dark-line: "#607080"
  dark-accent: "#a5c7ff"
  dark-on-accent: "#102a4c"
  dark-error: "#ffb4ab"
typography:
  title:
    fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "26px"
    fontWeight: 650
    lineHeight: 1.35
  body:
    fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "16px"
    lineHeight: 1.6
rounded:
  field: "6px"
  sheet: "12px"
spacing:
  gap: "8px"
  action-gap: "12px"
  paragraph: "20px"
  sheet-padding: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.field}"
    padding: "12px 18px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "12px"
---

# Design System: Secret Request

## Overview

依据已实现的表单整理：标题、申请 Agent、发起设备、申请时间、用途、剩余时间、一个或多个带标签的输入区及提交/拒绝。使用系统字体和本地资源；优先让本人确认正在给谁提供什么。每条申请独立打开；桌面端仅以通知引导到网页。

## Colors

浅色背景与白色表单承载内容；蓝色表示操作，红色表示错误。深色模式随系统切换，使用 frontmatter 对应的 dark 色值。

## Typography

正文 16px / 1.6，标题 26px / 1.35、650 字重。窄屏标题 24px。辅助文字 14px，页脚 13px；机密名称和用途允许换行。

## Layout

主体最大 600px，桌面外边距 64px、内边距 32px。520px 以下改为 24px 总横向留白、内边距 24px 20px；提交和拒绝纵向排列。显示控件禁止压缩和换行，输入可收缩。

字段组之间间距 24px，使用同一表单样式。机密支持一次填写多个字段。

## Elevation & Depth

使用背景色区分表单，不使用阴影或装饰动画。

## Shapes

表单圆角 12px，输入与按钮 6px。字段边框 1px；键盘焦点描边 3px、外偏移 3px。

## Components

按钮最小高度 46px，禁用时透明度 .55。密码字段默认隐藏；多行文本明确提示明文显示，选填字段明确标注。错误使用 alert，提交/拒绝显示各自的忙碌文案；请求结束时隐藏输入区。提交确认后尝试关闭输入页，浏览器禁止时显示关闭提示。Windows 与 macOS 只用按需通知打开输入页；webhook 同样指向该页。

只展示本次申请。请求结束后隐藏输入；断网明确表示提交尚未确认。Agent 名称由申请方声明，设备名称由服务接入配置识别。

## Do's and Don'ts

- 保持设备、用途和操作标签完整可读，保留明显焦点与键盘操作。
- 终态应明确显示已交付、拒绝或过期，避免继续显示可输入表单。
- 不在通知、错误信息或截图中放入真实机密，不添加外部字体、分析或远程图片。
