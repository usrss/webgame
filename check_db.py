import sys


def check_mysqldb():
    try:
        import MySQLdb
        print('MySQLdb version:', MySQLdb.__version__)
        conn = MySQLdb.connect(host='127.0.0.1', user='webgame_user', passwd='bradi8314', db='webgame_db', port=3306)
        cur = conn.cursor()
        cur.execute('SELECT 1 AS ok')
        print('MySQL connected, result:', cur.fetchone())
        conn.close()
    except Exception as e:
        print('MySQLdb ERROR:', type(e).__name__, e)


def check_psycopg():
    try:
        import psycopg
        print('psycopg3 available')
    except Exception as e:
        print('psycopg3 ERROR:', type(e).__name__, e)


if __name__ == '__main__':
    print('=== checking MySQLdb (MySQL, port 3306) ===')
    check_mysqldb()
    print('=== checking psycopg (PostgreSQL) ===')
    check_psycopg()
