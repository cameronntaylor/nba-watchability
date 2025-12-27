# - Odds API variables
API_KEY = 'e951efefc47b693e1bcebc240aac5479'
SPORT = 'americanfootball_nfl'
REGIONS = 'us' 
ODDS_FORMAT = 'decimal'
DATE_FORMAT = 'iso'


return pd.DataFrame(requests.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}/events', params={
    'api_key': API_KEY,
    'regions': REGIONS,
    'markets': 'h2h',
    'oddsFormat': ODDS_FORMAT,
    'dateFormat': DATE_FORMAT
    }).json())

def grab_featured_team_markets(max_date):
    featured_team_odds = requests.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}/odds', params={
            'api_key': API_KEY,
            'regions': REGIONS,
            'markets': TEAM_FEATURED_MARKETS,
            'oddsFormat': ODDS_FORMAT,
            'dateFormat': DATE_FORMAT
            }
            )
    featured_team_odds_data = featured_team_odds.json()
    rows = []
    for item in featured_team_odds_data:
        for bookmaker in item['bookmakers']:
            for market in bookmaker['markets']:
                for outcome in market['outcomes']:
                    row = {
                            'id': item['id'],
                            'game_start': item['commence_time'],
                            'game_home_team': item['home_team'],
                            'game_away_team': item['away_team'],
                            'bookmaker': bookmaker['key'],
                            'market_last_update': market['last_update'],
                            'market': market['key'],
                            'metric_name': outcome['name'],
                            'point': outcome.get('point', 'na'),
                            'price': outcome['price']
                    }
                    rows.append(row)
    featured_team_odds_df = pd.DataFrame(rows)
    featured_team_odds_thisweek_df = featured_team_odds_df[
        featured_team_odds_df['game_start'] < max_date 
    ]

    def convert_to_float(value):
        try:
            return float(value)
        except ValueError:
            return np.nan

    featured_team_odds_thisweek_df['point'] = featured_team_odds_thisweek_df['point'].apply(convert_to_float)


    moneyline_vegas_thisweek_df = featured_team_odds_thisweek_df[
        (featured_team_odds_thisweek_df['market']=='h2h') & 
        (featured_team_odds_thisweek_df['bookmaker'].isin(VALID_SPORTSBOOKS))  
        ].groupby(
            ['id', 'game_start', 'game_away_team', 'game_home_team', 'market', 'metric_name']
            )[['price']].median().reset_index().sort_values(by="game_start")

    print(moneyline_vegas_thisweek_df.shape)

    spreads_vegas_thisweek_df = featured_team_odds_thisweek_df[
        (featured_team_odds_thisweek_df['market']=='spreads') & 
        (featured_team_odds_thisweek_df['bookmaker'].isin(VALID_SPORTSBOOKS))  
        ].groupby(
            ['id', 'game_start', 'game_away_team', 'game_home_team', 'market', 'metric_name']
            )[['point', 'price']].median().reset_index().sort_values(by="game_start")

    print(spreads_vegas_thisweek_df.shape)

    over_under_vegas_thisweek_df = featured_team_odds_thisweek_df[
        (featured_team_odds_thisweek_df['metric_name']=='Over') & 
        (featured_team_odds_thisweek_df['market']=='totals') & 
        (featured_team_odds_thisweek_df['bookmaker'].isin(VALID_SPORTSBOOKS))  
        ].groupby(
            ['id', 'game_start', 'game_away_team', 'game_home_team', 'market']
            )[['point', 'price']].median().reset_index().sort_values(by="game_start")

    print(over_under_vegas_thisweek_df.shape)
    return moneyline_vegas_thisweek_df, spreads_vegas_thisweek_df, over_under_vegas_thisweek_df



def get_latest_date_for_this_weeks_matchups():
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    date_format = "%Y-%m-%d"
    given_date = datetime.datetime.strptime(today, date_format)
    if today < '2024-09-05':
        return '2024-09-11'
    return (given_date + datetime.timedelta(days=7)).strftime(date_format)