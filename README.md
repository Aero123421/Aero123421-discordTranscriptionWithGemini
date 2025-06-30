# Discord Transcription AI Bot

本リポジトリは Discord のボイスチャンネルでの発言を録音し、**Google Gemini 2.5 Flash API** を用いて文字起こし・整形を行う Bot の実装です。
設定したテキストチャンネルへ結果を自動投稿できます。

## 🎯 主な機能

- **自動録音機能**: 指定した**ボイスカテゴリ**または**個別ボイスチャンネル**へのユーザーの参加・退出を検知し、自動で録音を開始・終了します
- **カテゴリベース録音**: カテゴリ内のいずれかのボイスチャンネルでアクティビティがあった場合に録音が行われます
- **高品質文字起こし**: **Google Gemini 2.5 Flash API** を利用して音声データを文字起こしします
- **AI整形機能**: Gemini 2.5 Flash の思考機能を使ったテキスト整形も可能です
- **自動投稿**: 文字起こし結果を指定されたテキストチャンネルに **`.txt` ファイル形式**で投稿します


## 📋 必要なもの

- **Discord Bot トークン**
- **Google Gemini API キー**

## 🚀 セットアップ

### 1. Discord Bot の作成

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. "New Application" をクリックして新しいアプリケーションを作成
3. 左メニューの "Bot" をクリック
4. "Add Bot" をクリックしてボットを作成
5. "Token" をコピーして保存
6. "Privileged Gateway Intents" で以下を有効化：
   - **Message Content Intent**
   - **Server Members Intent** 
   - **Voice States Intent** （重要）

### 2. Google Gemini API キーの取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. Google アカウントでログイン
3. "Get API key" をクリック
4. 新しいAPIキーを作成してコピー

### 3. 環境設定



`.env.example` ファイルを編集して以下の値を設定：

```env
# Discord Bot設定
DISCORD_TOKEN=your_discord_bot_token_here

# Google Gemini API設定  
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL_NAME=gemini-2.5-flash

# Gemini 2.5 Flash思考機能設定
GEMINI_THINKING_BUDGET=-1  # -1=動的思考（推奨）, 0=思考オフ, 正の整数=トークン数
```

### 4. デプロイ方法

#### Python 直接実行

```bash
# 依存関係インストール
pip install -r requirements.txt

# Bot起動
python main.py
```


## 💬 使い方

Bot 起動後、Discord サーバーで以下のスラッシュコマンドを使用して設定を行います：

### スラッシュコマンド一覧

| コマンド | 説明 | 権限 |
|---------|------|------|
| `/set_voice_category` | 録音対象とするボイスチャンネルの**カテゴリ**を設定 | 全ユーザー |
| `/set_text_channel` | 文字起こし結果（`.txt`ファイル）を送信するテキストチャンネルを設定 | 全ユーザー |
| `/show_channels` | 現在設定されている録音対象と結果送信チャンネルを表示 | 全ユーザー |
| `/unset_channels` | 現在のサーバーで設定されているチャンネル情報をすべて解除 | 全ユーザー |


### 設定例

1. **カテゴリ設定**:
   ```
   /set_voice_category category:会議室カテゴリ
   ```

2. **結果送信チャンネル設定**:
   ```
   /set_text_channel channel:#transcripts
   ```

3. **設定確認**:
   ```
   /show_channels
   ```

## 🔧 Gemini 2.5 Flash 設定

### モデル特徴

- **高速処理**: 従来のFlashモデルより高速
- **思考機能**: 複雑な文字起こしでも論理的に処理
- **コスト効率**: 優れた価格性能比
- **多言語対応**: 日本語を含む24+言語に対応

### 思考機能設定 (`GEMINI_THINKING_BUDGET`)

| 値 | 説明 | 用途 |
|----|------|------|
| `0` | 思考機能オフ | 最高速・最低コスト |
| `-1` | 動的思考（推奨） | バランス重視 |
| `1-24576` | 固定トークン数 | 品質重視 |

## 📁 ファイル構成

```
discord-transcription-bot/
├── main.py                 # メインBotファイル
├── requirements.txt       # Python依存関係
├── .env.example          # 環境変数テンプレート
├── .gitignore           # Git除外設定
├── README.md            # このファイル
└── data/                # 設定ファイル保存ディレクトリ
    ├── channels.json    # 暗号化された設定（自動生成）

```

## 🔒 セキュリティ機能

- **設定暗号化**: Fernet暗号化による設定ファイル保護
- **環境変数管理**: 機密情報を環境変数で管理
- **ファイル権限制限**: 設定ファイルのアクセス権限を制限
- **非rootユーザー実行**: Dockerコンテナは非特権ユーザーで実行

## 📝 ログ機能

- **構造化ログ**: レベル別のログ出力
- **ローテーション**: Docker Composeでログローテーション設定済み
- **デバッグ**: `LOG_LEVEL=DEBUG` で詳細ログ表示

## ⚠️ 注意事項

### プライバシーとコンプライアンス
- **録音の同意**: ボイスチャンネルでの録音について事前に参加者の同意を得てください
- **Discord利用規約**: Discord の利用規約に従って使用してください
- **データ保護**: 録音データは一時的に保存され、処理後に自動削除されます

### 技術的制限
- **ファイルサイズ**: 音声ファイルは20MB以下
- **API制限**: Gemini APIの使用量制限に注意
- **同時録音**: サーバーごとに1つの録音セッションのみ





## 🙏 謝辞

- [Pycord](https://github.com/Pycord-Development/pycord) - Discord API ラッパー
- [Google Gemini](https://ai.google.dev/) - AI 文字起こし API


---

**⚡ Powered by Google Gemini 2.5 Flash**
