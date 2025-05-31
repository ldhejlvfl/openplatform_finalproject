from flask import Flask, request, abort
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, scoreboardv2, leaguestandings, playercareerstats, leaguegamefinder, boxscoretraditionalv2, leaguedashplayerstats, LeagueGameFinder
from nba_api.stats.static import teams as nba_teams
from datetime import datetime
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import pandas as pd
from dotenv import load_dotenv
import os

app = Flask(__name__)

load_dotenv()  # 讀取 .env 檔

# 設定 LINE Bot 的 Channel Access Token 和 Channel Secret
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 回應主程式
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 主訊息處理邏輯
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()

    if user_msg == "今日比賽":
        msg = get_today_scores()
    elif user_msg.endswith("上一場數據"):
        player_name = user_msg.replace("上一場數據", "").strip()
        msg = get_player_stats(player_name)
    elif user_msg == "球隊排名":
        msg = get_team_standings()
    elif user_msg.endswith("本季數據"):
        player_name = user_msg.replace("本季數據", "").strip()
        msg = get_player_season_stats(player_name)
    elif user_msg.startswith("球隊 "):
        teams = user_msg.replace("球隊 ", "").strip().split()
        if len(teams) == 2:
            msg = get_recent_matchups(teams[0].upper(), teams[1].upper())
        else:
            msg = "請輸入正確格式，例如：球隊 LAL BOS"
    elif user_msg == "得分榜":
        msg = get_top_scorers()
    else:
        msg = (
        "請輸入以下指令之一來查詢資料：\n"
        "今日比賽\n"
        "[球員姓名] 上一場數據（例如：LeBron James 上一場數據）\n"
        "[球員姓名] 本季數據（例如：Stephen Curry 本季數據）\n"
        "球隊排名\n"
        "得分榜\n"
        "球隊 [縮寫1] [縮寫2]（查詢兩隊近期交手，例：球隊 LAL BOS）"
    )

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

# 取得今天的比賽比分(今日比賽)
def get_today_scores():
    today = datetime.today().strftime('%m/%d/%Y')
    scoreboard = scoreboardv2.ScoreboardV2(game_date=today)
    games = scoreboard.get_data_frames()[0]
    linescores = scoreboard.get_data_frames()[1]

    if games.empty:
        return "今天沒有 NBA 比賽喔！"

    game_results = "【今日比賽比分】\n"
    for game_id in games['GAME_ID'].unique():
        teams = linescores[linescores['GAME_ID'] == game_id]
        if teams.shape[0] == 2:
            away = teams.iloc[0]
            home = teams.iloc[1]
            game_results += f"{away['TEAM_ABBREVIATION']} {away['PTS']} - {home['PTS']} {home['TEAM_ABBREVIATION']}\n"
    return game_results

# (Stephen Curry 上一場數據)
def get_player_stats(player_name):
    found_players = players.find_players_by_full_name(player_name)
    if not found_players:
        return f"找不到名為「{player_name}」的球員，請確認名字是否正確（需英文全名）"
    player_id = found_players[0]['id']

    playoff_log = playergamelog.PlayerGameLog(player_id=player_id, season_type_all_star='Playoffs')
    df = playoff_log.get_data_frames()[0]

    if df.empty:
        regular_log = playergamelog.PlayerGameLog(player_id=player_id, season_type_all_star='Regular Season')
        df = regular_log.get_data_frames()[0]

    if df.empty:
        return f"查無 {player_name} 的比賽紀錄。"

    latest = df.iloc[0]

    # 取投籃、三分、罰球命中率及進球/出手數
    fg_pct = round(latest['FG_PCT']*100,1)
    fg_made = latest['FGM']
    fg_attempt = latest['FGA']

    fg3_pct = round(latest['FG3_PCT']*100,1)
    fg3_made = latest['FG3M']
    fg3_attempt = latest['FG3A']

    ft_pct = round(latest['FT_PCT']*100,1)
    ft_made = latest['FTM']
    ft_attempt = latest['FTA']

    msg = (
        f"{player_name} 最新一場比賽數據 ({latest['GAME_DATE']})\n"
        f"對戰隊伍：{latest['MATCHUP']}\n"
        f"上場時間：{latest['MIN']} 分鐘\n"
        f"得分：{latest['PTS']} 分\n"
        f"助攻：{latest['AST']} 次\n"
        f"籃板：{latest['REB']} 個\n"
        f"抄截：{latest['STL']} 次\n"
        f"阻攻：{latest['BLK']} 次\n"
        f"投籃命中率：{fg_pct}% ({fg_made}/{fg_attempt})\n"
        f"三分命中率：{fg3_pct}% ({fg3_made}/{fg3_attempt})\n"
        f"罰球命中率：{ft_pct}% ({ft_made}/{ft_attempt})\n"
        f"正負值：{latest['PLUS_MINUS']}\n"
        f"犯規：{latest['PF']} 次"
    )
    return msg

# (球隊排名)
def get_team_standings():
    standings = leaguestandings.LeagueStandings()
    df = standings.get_data_frames()[0]

    east = df[df['Conference'] == 'East'].sort_values('PlayoffRank').head(8)
    west = df[df['Conference'] == 'West'].sort_values('PlayoffRank').head(8)

    # 計算所有隊伍中最長的隊名，統一欄位寬度
    max_len = max(df['TeamName'].str.len())

    msg = "🏀 東區排名 Top 8\n"
    for i, (_, row) in enumerate(east.iterrows(), start=1):
        team = row['TeamName'].ljust(max_len)
        msg += f"{i:>2}. {team}  {row['WINS']:>2}W {row['LOSSES']:>2}L\n"

    msg += "\n====================\n\n🏀 西區排名 Top 8\n"
    for i, (_, row) in enumerate(west.iterrows(), start=1):
        team = row['TeamName'].ljust(max_len)
        msg += f"{i:>2}. {team}  {row['WINS']:>2}W {row['LOSSES']:>2}L\n"

    return msg

# (Stephen Curry 本季數據)
def get_player_season_stats(player_name):
    found_players = players.find_players_by_full_name(player_name)
    if not found_players:
        return f"找不到名為「{player_name}」的球員，請確認名字是否正確（需英文全名）"
    
    player_id = found_players[0]['id']
    career = playercareerstats.PlayerCareerStats(player_id=player_id)
    df = career.get_data_frames()[0]

    # 篩選出 Regular Season 本季數據（最新一季）
    regular_seasons = df[df['SEASON_ID'].str.startswith('2')]  # 篩選 NBA 例行賽
    if regular_seasons.empty:
        return f"查無 {player_name} 本季例行賽數據。"

    # 取得最新一季（season排序最大）
    latest_season = regular_seasons.iloc[-1]

    games_played = latest_season['GP']
    if games_played == 0:
        return f"{player_name} 本季尚無出賽資料。"

    avg_min = latest_season['MIN'] / games_played
    avg_pts = latest_season['PTS'] / games_played
    avg_ast = latest_season['AST'] / games_played
    avg_reb = latest_season['REB'] / games_played
    avg_stl = latest_season['STL'] / games_played
    avg_blk = latest_season['BLK'] / games_played
    avg_tov = latest_season['TOV'] / games_played

    msg = (
        f"{player_name} 本季 ({latest_season['SEASON_ID']}) 平均數據：\n"
        f"出賽場數：{games_played} 場\n"
        f"場均上場時間：{avg_min:.1f} 分鐘\n"
        f"場均得分：{avg_pts:.1f}\n"
        f"場均助攻：{avg_ast:.1f}\n"
        f"場均籃板：{avg_reb:.1f}\n"
        f"場均抄截：{avg_stl:.1f}\n"
        f"場均阻攻：{avg_blk:.1f}\n"
        f"場均失誤：{avg_tov:.1f}\n"
        f"投籃命中率：{latest_season['FG_PCT']*100:.1f}%\n"
        f"三分命中率：{latest_season['FG3_PCT']*100:.1f}%\n"
        f"罰球命中率：{latest_season['FT_PCT']*100:.1f}%"
    )

    return msg


def get_team_id_by_abbr(team_abbr):
    all_teams = nba_teams.get_teams()
    for t in all_teams:
        if t['abbreviation'] == team_abbr:
            return t['id']
    return None

# (球隊 LAL BOS)
def get_recent_matchups(team1_abbr, team2_abbr):
    try:
        team1_id = get_team_id_by_abbr(team1_abbr)
        team2_id = get_team_id_by_abbr(team2_abbr)

        if not team1_id or not team2_id:
            return f"找不到隊伍：{team1_abbr} 或 {team2_abbr}"

        gamefinder = leaguegamefinder.LeagueGameFinder(team_id_nullable=team1_id, season_type_nullable='Regular Season')
        df = gamefinder.get_data_frames()[0]

        # 篩選出對手是 team2 的比賽（MATCHUP 中包含 team2 縮寫）
        df_matchups = df[df['MATCHUP'].str.contains(team2_abbr)]

        if df_matchups.empty:
            return f"{team1_abbr} 與 {team2_abbr} 近期沒有交手紀錄。"

        df_recent = df_matchups.sort_values(by='GAME_DATE', ascending=False).head(3)

        msg = f"{team1_abbr} vs {team2_abbr} 近三次交手：\n\n"
        for _, row in df_recent.iterrows():
            game_id = row['GAME_ID']

            boxscore = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id)
            teams_df = boxscore.get_data_frames()[1]

            team1_score = None
            team2_score = None
            for _, team_row in teams_df.iterrows():
                if team_row['TEAM_ABBREVIATION'] == team1_abbr:
                    team1_score = team_row['PTS']
                if team_row['TEAM_ABBREVIATION'] == team2_abbr:
                    team2_score = team_row['PTS']

            if team1_score is not None and team2_score is not None:
                if team1_score > team2_score:
                    result = f"🏆{team1_abbr} 勝"
                elif team1_score < team2_score:
                    result = f"🏆{team2_abbr} 勝"
                

                msg += (f"{row['GAME_DATE']}\n{team1_abbr} {team1_score} : {team2_score} {team2_abbr}\n{result}\n\n")
            else:
                msg += f"{row['GAME_DATE']} - 比賽資料不完整\n"

        return msg

    except Exception as e:
        return f"查詢交手紀錄時發生錯誤：{str(e)}"

# (得分榜)
def get_top_scorers():
    try:
        stats = leaguedashplayerstats.LeagueDashPlayerStats(season='2024-25', season_type_all_star='Regular Season')
        df = stats.get_data_frames()[0]

        # 確保出場場次不為0，然後計算場均得分（若PTS是總得分）
        df = df[df['GP'] > 0].copy()
        df['PTS_PER_GAME'] = df['PTS'] / df['GP']

        top20 = df.sort_values(by='PTS_PER_GAME', ascending=False).head(20)

        msg = "🏀 本季得分榜 Top 20\n\n"
        for i, (_, row) in enumerate(top20.iterrows(), start=1):
            player_name = row['PLAYER_NAME']
            pts_pg = row['PTS_PER_GAME']
            gp = row['GP']
            msg += f"{i}. {player_name}: 場均{pts_pg:.1f}分\n"

        return msg
    except Exception as e:
        return f"取得得分榜資料時發生錯誤：{str(e)}"



if __name__ == "__main__":
    app.run(debug=True)


