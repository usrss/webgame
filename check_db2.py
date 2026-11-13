import sys

def try_mysql():
    try:
        import MySQLdb
        conn = MySQLdb.connect(host="127.0.0.1", user="webgame_user", passwd="bradi8314", db="webgame_db", port=3306, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        print("MySQL OK:", cur.fetchone())
        conn.close()
    except Exception as e:
        print("MySQL ERROR:", type(e).__name__, e)

def try_pg():
    try:
        import psycopg
        conn = psycopg.connect(host="127.0.0.1", dbname="webgame_db", user="webgame_user", password="bradi8314", port=5432, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version()")
        print("PostgreSQL OK:", cur.fetchone())
        conn.close()
    except Exception as e:
        print("PostgreSQL ERROR:", type(e).__name__, e)

try_mysql()
try_pg()
