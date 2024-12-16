import os
import psycopg2
import hvac
import sqlparse
import json
import sys

dangerous_keywords = ["CREATE", "ALTER", "DROP", "RENAME", "TRUNCATE", "GRANT", "REVOKE", "VACUUM", "ANALYZE", "REINDEX", "REFRESH MATERIALIZED VIEW", "SET", "RESET", "SHOW", "LOCK", "DISCARD", "CHECKPOINT", "LISTEN", "NOTIFY", "UNLISTEN", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"]
ddl_keywords = ["SET", "RESET", "SHOW", "LISTEN", "NOTIFY", "UNLISTEN", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE"]
combine_list_keywords = dangerous_keywords + ddl_keywords

def get_secrets_from_vault(vault_url, vault_token, kv_engine, secret_path):
    try:
        client = hvac.Client(url=vault_url, token=vault_token)
        if not client.is_authenticated():
            raise ValueError("Ошибка аутентификации в Vault")
        secrets = client.secrets.kv.v2.read_secret_version(path=secret_path, mount_point=kv_engine, raise_on_deleted_version=True)
        return secrets["data"]["data"]
    except Exception as e:
        raise RuntimeError(f"Не удалось получить секреты из Vault: {e}")

def check_file_for_dangerous_keywords(file_path):
    found_keywords = []
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()
    for keyword in dangerous_keywords:
        if keyword.lower() in content.lower():
            found_keywords.append(keyword)
    if found_keywords:
        return f"\n\033[91m[ERROR]\033[0m: Найдено меняющее структуру ключевое слово: {', '.join(found_keywords)}"
    else:
        return "\033[92mOk\033[0m"

def explain_query(conn, query):
    cursor = conn.cursor()
    try:
        if any(keyword in query.upper() for keyword in combine_list_keywords):
            return f"\033[93mWARNING\033[0m: Пропуск неподдерживаемой команды при EXPLAIN:\n{query.strip()}"
        cursor.execute("EXPLAIN " + query)
        result = cursor.fetchall()
        explain_output = "\n".join([row[0] for row in result])
        cursor.close()
        return f"[INFO] Вывод EXPLAIN:\n{explain_output}"
    except Exception as e:
        conn.rollback()
        cursor.close()
        return f"\033[91m[ERROR]\033[0m: Ошибка при выполнении EXPLAIN: {e}"

def execute_scripts_from_files(conn, directory_path, apply=False):
    result_map = {}
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.sql'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as script_file:
                    script = script_file.read()

                print(f"[INFO] Проверка файла: {file_path}")

                print(f"[INFO] Проверка на наличие деструктивных команд: {check_file_for_dangerous_keywords(file_path)}")

                script = sqlparse.format(script, strip_comments=True)
                queries = sqlparse.split(script)
                for query in queries:
                    query = query.strip()
                    if query:
                        print(explain_query(conn, query))

                if apply:
                    cursor = conn.cursor()
                    try:
                        cursor.execute(script)
                        conn.commit()
                        cursor.close()
                        result_map[file] = True
                        print(f"\033[92m[INFO] Скрипт применен: {file_path}\033[0m")
                    except Exception as e:
                        print(f"\033[91m[ERROR]\033[0m Ошибка при применении скрипта {file_path}: {e}")
                        conn.rollback()
                        cursor.close()
                        result_map[file] = False
    return result_map

def process_directory(directory_path, apply=False):

    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".sql"):
                found_sql_files = True
                break

    if not found_sql_files:
        print(f"\033[91m[ERROR]\033[0m Не найдено ни одного файла с расширением .sql")
        sys.exit(1)

    vault_required_env_vars = ['VAULT_URL', 'VAULT_TOKEN', 'KV_ENGINE', 'SECRET_PATH']
    vault_env = {var: os.environ.get(var) for var in vault_required_env_vars}
    is_vault_config_complete = all(vault_env.values())

    db_required_env_vars = ['DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD']
    db_env = {var: os.environ.get(var) for var in db_required_env_vars}
    is_db_config_complete = all(db_env.values())

    if is_vault_config_complete:
        secrets = get_secrets_from_vault(
            vault_env['VAULT_URL'],
            vault_env['VAULT_TOKEN'],
            vault_env['KV_ENGINE'],
            vault_env['SECRET_PATH']
        )
        db_host = secrets['host']
        db_port = int(secrets['port'])
        db_name = secrets['dbname']
        db_username = secrets['username']
        db_password = secrets['password']

    elif is_db_config_complete:
        db_host = db_env['DB_HOST']
        db_port = int(db_env['DB_PORT'])
        db_name = db_env['DB_NAME']
        db_username = db_env['DB_USER']
        db_password = db_env['DB_PASSWORD']

    else:
        raise ValueError("Необходимо задать либо полный набор переменных окружения для Vault (VAULT_URL, VAULT_TOKEN, KV_ENGINE, SECRET_PATH), либо для базы данных (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD)")

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_username,
        password=db_password
    )

    result_map = execute_scripts_from_files(conn, directory_path, apply)
    conn.close()

    with open('result_map.json', 'w', encoding='utf-8') as result_file:
        import json
        json.dump(result_map, result_file, ensure_ascii=False, indent=4)

    return result_map

def string_to_bool(str):
  return str.lower() in ['true', 'yes', '1']

if __name__ == "__main__":
    directory_path = os.environ.get('DIRECTORY_PATH')
    apply_flag = os.environ.get('APPLY')
    apply_flag = string_to_bool(apply_flag)
    if not directory_path:
        raise ValueError("Переменная окружения DIRECTORY_PATH должна быть задана")

    applied_files_map = process_directory(directory_path, apply=apply_flag)
    output_data = {
        "status": "true",
        "comment": "Скрипты применены успешно",
        "applied_files": [],
        "not_applied_files": []
    }
    for file, status in applied_files_map.items():
        if status:
            output_data["applied_files"].append(file)
        else:
            output_data["not_applied_files"].append(file)
    with open("output.json", "w") as json_file:
        json.dump(output_data, json_file, ensure_ascii=False)
    print(json.dumps(output_data, ensure_ascii=False))