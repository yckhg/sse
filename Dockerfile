FROM odoo:19.0

# 엔터프라이즈 소스 복사
COPY odoo-19.0+e.20260101/odoo /usr/lib/python3/dist-packages/odoo

WORKDIR /

EXPOSE 8069 8072

# Odoo 실행
CMD ["odoo"]
