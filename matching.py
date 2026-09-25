"""在服务器上计算参与者与项目的可解释匹配指数。"""


def normalize(values):
    return {value.strip().casefold() for value in values if value.strip()}


def calculate(user, project):
    """资料完整时返回 0–100 分及分项；资料不足时返回 None。"""
    if not user or not user["skills"] or not user["interests"] or not user["hours"]:
        return None
    skills = normalize(user["skills"])
    interests = normalize(user["interests"])
    skill_hits = [value for value in project["needs"] if value.casefold() in skills]
    topic_hits = [value for value in project["topics"] if value.casefold() in interests]
    skill_points = round(60 * len(skill_hits) / len(project["needs"]))
    topic_points = round(25 * len(topic_hits) / len(project["topics"]))
    time_points = round(15 * min(user["hours"] / project["minHours"], 1))
    return {
        "total": skill_points + topic_points + time_points,
        "skillPoints": skill_points,
        "topicPoints": topic_points,
        "timePoints": time_points,
        "skillHits": skill_hits,
        "topicHits": topic_hits,
    }
