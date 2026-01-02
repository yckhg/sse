FROM odoo:19.0

# 엔터프라이즈 소스 복사
COPY odoo-19.0+e.20260101/odoo /usr/lib/python3/dist-packages/odoo

# 초기화 스크립트 복사
COPY init-odoo.sh /init-odoo.sh

WORKDIR /

EXPOSE 8069 8072

# 초기화 후 Odoo 실행
ENTRYPOINT ["/bin/bash", "-c"]
CMD ["/init-odoo.sh && odoo"]
