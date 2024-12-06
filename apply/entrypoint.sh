#!/bin/sh
python /sql.py

if [ ! -f result_map.json ]; then
  echo "Файл result_map.json не найден!"
  exit 1
fi

map_output=$(jq -r 'to_entries | map("\(.key)=\(.value)") | join(",")' result_map.json)

echo "result_map=$map_output" >> $GITEA_OUTPUT
echo "map применненных скриптов сохранен в output под ключом result_map"
