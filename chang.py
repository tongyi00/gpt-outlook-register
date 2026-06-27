# -*- coding: UTF-8 -*-
"""
@description:
@file: chang.py
@author: TongMengJun
@date: 2026/6/26 19:29
"""
def convert_file(input_path="outlook.txt", output_path="outlook_converted.txt"):
    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split("----")

        # 基本校验
        if len(parts) != 4:
            print(f"跳过异常行: {line}")
            continue

        email = parts[0]
        password = parts[1]
        refresh_token = parts[2]
        client_id = parts[3]

        new_line = "----".join([
            email,
            password,
            client_id,
            refresh_token
        ])

        result.append(new_line)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(result))

    print(f"转换完成，共处理 {len(result)} 条数据")


if __name__ == "__main__":
    convert_file()
