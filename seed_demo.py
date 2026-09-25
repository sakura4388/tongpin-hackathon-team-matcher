"""向当前数据库写入一组可重复查看的黑客松演示资料。"""

import os

from werkzeug.security import generate_password_hash

from app import app, db, init_db


DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo12345!")

PEOPLE = [
    ("演示·许一诺", "产品策划", "产品|用户研究", "教育|AI", 12,
     "想做一个让学习更轻松的小工具，正在找开发和设计伙伴。"),
    ("演示·阿澈", "Python 开发者", "Python|数据分析", "教育|AI", 10,
     "喜欢把想法写成能用的程序，也愿意处理数据。"),
    ("演示·小羽", "设计师", "视觉设计|前端", "教育|社区", 8,
     "擅长把复杂的信息整理成清楚的页面。"),
    ("演示·苏禾", "前端开发者", "前端|UI设计", "环保|社区", 6,
     "希望用网页帮助大家发现身边的绿色资源。"),
]


def main():
    if len(DEMO_PASSWORD) < 8:
        raise ValueError("演示密码至少需要 8 位。")
    with app.app_context():
        init_db()
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS demo_seed (name TEXT PRIMARY KEY)")
            done = connection.execute("SELECT 1 FROM demo_seed WHERE name='v1'").fetchone()
            if done:
                connection.execute("COMMIT")
                print("演示数据已经存在，本次未重复写入。")
                return

            names = [row[0] for row in PEOPLE]
            placeholders = ",".join("?" for _ in names)
            conflict = connection.execute(
                f"SELECT nickname FROM users WHERE nickname IN ({placeholders})", names
            ).fetchone()
            if conflict:
                raise ValueError(f"昵称 {conflict['nickname']} 已存在；未写入演示数据。")

            ids = {}
            for nickname, role, skills, interests, hours, bio in PEOPLE:
                cursor = connection.execute("""
                    INSERT INTO users
                    (nickname,password_hash,role,skills,interests,hours,bio)
                    VALUES (?,?,?,?,?,?,?)
                """, (nickname, generate_password_hash(DEMO_PASSWORD), role, skills,
                      interests, hours, bio))
                ids[nickname] = cursor.lastrowid

            first = connection.execute("""
                INSERT INTO projects
                (owner_id,title,description,needs,topics,min_hours,capacity)
                VALUES (?,?,?,?,?,?,?)
            """, (ids["演示·许一诺"], "演示·课间灵感站",
                  "用一个小工具帮学生整理知识点，把课间时间还给探索与休息。",
                  "Python|视觉设计", "教育|AI", 8, 4)).lastrowid
            second = connection.execute("""
                INSERT INTO projects
                (owner_id,title,description,needs,topics,min_hours,capacity)
                VALUES (?,?,?,?,?,?,?)
            """, (ids["演示·苏禾"], "演示·绿色补给地图",
                  "把社区回收点、绿色活动和闲置交换地点整理到一张地图上。",
                  "前端|数据分析", "环保|社区", 6, 3)).lastrowid

            connection.executemany(
                "INSERT INTO memberships (project_id,user_id) VALUES (?,?)",
                [(first, ids["演示·许一诺"]), (first, ids["演示·小羽"]),
                 (second, ids["演示·苏禾"])],
            )
            connection.executemany("""
                INSERT INTO applications (project_id,user_id,status) VALUES (?,?,?)
            """, [(first, ids["演示·小羽"], "accepted"),
                  (first, ids["演示·阿澈"], "pending")])
            connection.execute("INSERT INTO demo_seed (name) VALUES ('v1')")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    print("已写入 4 张名片、2 个项目、1 条待处理申请和 1 条已接受申请。")
    print("演示账号使用同一密码：" + DEMO_PASSWORD)


if __name__ == "__main__":
    main()
