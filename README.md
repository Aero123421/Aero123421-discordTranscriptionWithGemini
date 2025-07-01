# Discord文字起こしAI Bot

このリポジトリは、Discordのボイスチャンネルでの会話を録音し、**Google Gemini API** を使用して文字起こしを行うBotです。結果は設定されたテキストチャンネルに自動的に投稿されます。

## 🎯 主な機能

- **自動録音**: 指定されたボイスチャンネルでのユーザーの出入りを検知し、自動で録音を開始・終了します。
- **高品質な文字起こし**: **Google Gemini API** を利用して、正確な音声からテキストへの変換を実現します。
- **AIによる整形**: Geminiの能力を活用し、読みやすいように文字起こし結果を整形することも可能です。
- **自動投稿**: 文字起こし結果を `.txt` ファイルとして指定のテキストチャンネルに投稿します。
- **シンプルな設定管理**: サーバーごとの設定を `channels.json` ファイルで管理します。
- **環境変数による管理**: `.env` ファイルで簡単に設定を行えます。

## 📋 必要なもの

- **Python 3.9 以上**
- **ffmpeg** のインストール
- **Discord Bot トークン**
- **Google Gemini API キー**

## 🚀 セットアップ

### 1. Discord Botの作成

1. [Discord Developer Portal](https://discord.com/developers/applications)にアクセスします。
2. 「New Application」をクリックして新しいアプリケーションを作成します。
3. 「Bot」タブに移動し、「Add Bot」をクリックします。
4. Botの**トークン**をコピーします。
5. 以下の **Privileged Gateway Intents** を有効にします:
   - **Message Content Intent**
   - **Server Members Intent**
   - **Voice State Intent** (重要)

### 2. Google Gemini APIキーの取得

1. [Google AI Studio](https://aistudio.google.com/)にアクセスします。
2. Googleアカウントでサインインします。
3. 「Get API key」をクリックして新しいAPIキーを作成します。

### 3. 環境設定

リポジトリをクローンし、環境変数を設定します。

```bash
git clone <リポジトリURL>
cd <リポジトリフォルダ>
pip install -r requirements.txt
cp .env.example .env
```

`.env` ファイルを編集して、以下の値を設定します。

```env
# Discord Bot設定
DISCORD_TOKEN=ここにDiscordボットトークンを入力

# Google Gemini API設定
GEMINI_API_KEY=ここにGemini APIキーを入力
GEMINI_MODEL_NAME=gemini-1.5-flash

# Gemini思考予算
GEMINI_THINKING_BUDGET=-1  # -1=動的(推奨), 0=オフ, 正の整数=トークン数
```

### 4. Botの実行

```bash
python main.py
```

**注意**: `ffmpeg` がシステムにインストールされ、PATHが通っていることを確認してください。

## 💬 使い方

Botが起動したら、Discordサーバーで以下のスラッシュコマンドを使用して設定を行います。

### スラッシュコマンド一覧

| コマンド | 説明 | 権限 |
|---|---|---|
| `/set_voice_category` | 録音対象のボイスチャンネルカテゴリを設定します。 | 全員 |
| `/set_text_channel` | 文字起こし結果を送信するテキストチャンネルを設定します。 | 全員 |
| `/show_channels` | 現在設定されているチャンネルを表示します。 | 全員 |
| `/unset_channels` | サーバーのチャンネル設定をすべて解除します。 | 全員 |
| `/stop` | 進行中の録音を手動で停止します。 | **管理者のみ** |

### 設定例

1. **カテゴリの設定**:
   ```
   /set_voice_category category:会議室
   ```

2. **結果を送信するチャンネルの設定**:
   ```
   /set_text_channel channel:#文字起こし結果
   ```

3. **設定の確認**:
   ```
   /show_channels
   ```

## 📁 ファイル構成

```
discord-transcription-bot/
├── main.py                 # メインのBotファイル
├── config.py              # Pydantic設定管理
├── config_manager.py      # 設定管理 (JSON)
├── gemini_client.py       # Gemini APIクライアント
├── requirements.txt       # Python依存関係
├── .env.example          # 環境変数テンプレート
├── .gitignore           # Git無視設定
├── README.md            # このファイル
└── channels.json        # サーバー設定 (自動生成)
```

## ⚠️ 注意事項

### プライバシーとコンプライアンス
- **同意の取得**: ボイスチャンネルを録音する前に、必ず参加者から同意を得てください。
- **Discord利用規約**: このBotはDiscordの利用規約に従って使用してください。
- **データ取扱い**: 録音データは処理のために一時的に保存され、自動的に削除されます。

### 技術的な制限
- **ファイルサイズ**: 音声ファイルはGemini APIの制限に従います（現在、音声ファイルは1時間の制限があります）。
- **API制限**: Gemini APIの使用量制限にご注意ください。
- **同時録音**: サーバーごとに1つの録音セッションのみサポートされます。

## 🙏 謝辞

- [Pycord](https://github.com/Pycord-Development/pycord) - Discord APIラッパー
- [Google Gemini](https://ai.google.dev/) - AI文字起こしAPI

---

**⚡ Powered by Google Gemini**
