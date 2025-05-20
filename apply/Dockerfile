FROM git.softline.com/registry/python-image:v4
COPY sql.py /sql.py
ENTRYPOINT ["sh", "-c", "python /sql.py && echo \"::set-output name=output_data::$(cat psqloutput.json)\""]