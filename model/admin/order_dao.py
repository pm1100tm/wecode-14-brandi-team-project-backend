import pymysql
import traceback
from utils.custom_exceptions import (OrderDoesNotExist,
                                     UnableToUpdate,
                                     DoesNotOrderDetail,
                                     DeniedUpdate,
                                     )

class OrderDao:
    """ Persistence Layer

        Attributes: None

        Author: 김민서

        History:
            2020-2012-29(김민서): 초기 생성
            2020-12-30(김민서): 1차 수정
            2020-12-31(김민서): 2차 수정
            2020-01-05(김민서): get_order_list_dao - sql문 정리
    """


    def get_order_list_dao(self, connection, data):
        # 카운트 sql
        total_count_sql = """
                    SELECT COUNT(*) AS total_count
                """

        # 기본 sql
        sql = """
                    SELECT 
                        order_items.id
                        , order_items.created_at AS created_at_date
                        , orders.order_number AS order_number
                        , order_items.order_detail_number AS order_detail_number
                        , products.name AS product_name
                        , orders.sender_name AS customer_name
                        , orders.sender_phone AS customer_phone
                """

        # 마스터 공통 sql
        master_sql = """
                    , sellers.name AS seller_name
                    , orders.total_price AS total_price
                    , order_item_status_types.name AS `status`
                """

        # 필터링 sql
        extra_sql = """
                    FROM order_items
                        INNER JOIN orders 
                            ON order_items.order_id = orders.id
                        INNER JOIN products 
                            ON order_items.product_id = products.id
                        INNER JOIN sellers
                            ON products.seller_id = sellers.account_id
                        INNER JOIN stocks
                            ON order_items.stock_id = stocks.id
                        INNER JOIN colors 
                            ON stocks.color_id = colors.id
                        INNER JOIN sizes
                            ON stocks.size_id = sizes.id
                        INNER JOIN order_item_status_types
                            ON order_items.order_item_status_type_id = order_item_status_types.id
                    WHERE
                        order_items.is_deleted = 0
                        AND order_item_status_types.id = %(status)s
                """

        permission = data['permission']
        status = data['status']

        # 마스터인 경우 공통 sql 추가
        if permission == 1:
            sql += master_sql

        # 상품 준비 관리 상태가 아닌 경우
        if not status == 1:
            sql += ", order_items.updated_at AS updated_at_date"

        # 마스터인 동시에 배송중 상태가 아닌 경우
        if (permission == 1) and (not status == 2):
            sql += """
                , CONCAT(colors.`name`, '/', sizes.`name`) AS option_information
                , stocks.extra_cost AS option_extra_cost
                , order_items.quantity AS quantity
            """

        # 셀러인 동시에 배송중 상태가 아닌 경우
        if (permission == 2) and (not status == 3):
            sql += """
                , order_item_status_types.`name` AS `status`
            """

        # 셀러인 동시에 상품 준비 상태이거나 구매 확정 상태인 경우
        if (permission == 2) and (status == 1 or status == 8):
            sql += """
                , CONCAT(colors.name, '/', sizes.name) AS option_information
                , order_items.quantity AS quantity
            """

        # 필터링 조건 추가
        # 권한 조건 확인
        if data["permission"] == 2:
            extra_sql += "AND sellers.account_id = %(account)s"

        # 검색어 조건
        if data['number']:
            extra_sql += " AND orders.order_number = %(number)s"
        if data['detail_number']:
            extra_sql += " AND order_items.order_detail_number = %(detail_number)s"
        if data['sender_name']:
            extra_sql += " AND orders.sender_name = %(sender_name)s"
        if data['sender_phone']:
            extra_sql += " AND orders.sender_phone = %(sender_phone)s"
        if data['seller_name']:
            extra_sql += " AND sellers.name = %(seller_name)s"
        if data['product_name']:
            extra_sql += " AND products.name LIKE %(product_name)s"

        # 날짜 조건
        if data['start_date'] and data['end_date']:
            extra_sql += """ AND order_items.updated_at BETWEEN CONCAT(%(start_date)s, ' 00:00:00') AND CONCAT(%(end_date)s, ' 23:59:59')
            """

        # 셀러 속성 조건
        if data['attributes']:
            extra_sql += " AND sellers.seller_attribute_type_id IN %(attributes)s"

        # 정렬 조건
        if data['status'] == 1:
            if data['order_by'] == 'recent':
                extra_sql += " ORDER BY order_items.id DESC"
            else:
                extra_sql += " ORDER BY order_items.id ASC"
        else:
            if data['order_by'] == 'recent':
                extra_sql += " ORDER BY order_items.updated_at DESC"
            else:
                extra_sql += " ORDER BY order_items.updated_at ASC"

        total_count_sql += extra_sql
        sql += extra_sql

        # 페이지 조건
        sql += " LIMIT %(page)s, %(length)s;"

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, data)
            list = cursor.fetchall()
            if not list:
                raise OrderDoesNotExist('주문 내역이 없습니다.')
            cursor.execute(total_count_sql, data)
            count = cursor.fetchone()

            return {'total_count': count['total_count'], 'order_lists': list}


    def update_order_status_dao(self, connection, data):
        """ 주문 상태 업데이트

            Args:
                connection : 데이터베이스 연결 객체
                data       : 비지니스 레이어에서 넘겨 받은 data 객체

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            UPDATE order_items
            SET order_item_status_type_id = %(new_status)s
            WHERE id IN %(ids)s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            affected_row = cursor.execute(sql, data)
            if affected_row != data['count_new_status']:
                raise UnableToUpdate('업데이트가 불가합니다.')

    def add_order_history_dao(self, connection, data):
        """ 주문 상태 변경 히스토리 생성

            Args:
                connection : 데이터베이스 연결 객체
                data       : 비지니스 레이어에서 넘겨 받은 data 객체

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            INSERT
            INTO order_item_histories (order_item_id, order_item_status_type_id, updater_id)
            VALUES (%s, %s, %s);
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            created_rows = cursor.executemany(sql, data['update_data'])
            if created_rows != data['count_new_status']:
                raise UnableToUpdate('업데이트가 불가합니다.')


class OrderDetailDao():
    """ Persistence Layer

        Attributes: None

        Author: 김민서

        History:
            2021-01-01(김민서): 초기 생성
    """

    def get_order_info_dao(self, connection, order_item_id):
        """ 주문 정보

            Args:
                connection   : 데이터베이스 연결 객체
                order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                [{'order_id': 2, 'order_number': '20201225000000002',
                'order_purchased_date': datetime.datetime(2020, 12, 31, 13, 25, 3), 'total_price': Decimal('9000')}]

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT 
                `order`.id AS order_id, 
                `order`.order_number AS order_number,
                `order`.created_at AS order_purchased_date,
                `order`.total_price AS total_price
            FROM order_items AS order_item
                INNER JOIN orders AS `order` 
                    ON order_item.order_id = `order`.id
                INNER JOIN delivery_memo_types AS delivery_memo
                    ON `order`.delivery_memo_type_id = delivery_memo.id
                INNER JOIN products AS product 
                    ON order_item.product_id = product.id
                INNER JOIN sellers AS seller 
                    ON product.seller_id = seller.account_id
                INNER JOIN stocks AS stock 
                    ON order_item.stock_id = stock.id
                INNER JOIN colors AS color 
                    ON stock.color_id = color.id
                INNER JOIN sizes AS size 
                    ON stock.size_id = size.id
                INNER JOIN order_item_status_types AS order_item_status 
                    ON order_item.order_item_status_type_id = order_item_status.id
            WHERE order_item.id = %s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchall()
            if not result:
                raise DoesNotOrderDetail('주문 상세 정보가 존재하지 않습니다.')
            return result


    def get_order_detail_info_dao(self, connection, order_item_id):
        """ 주문 상세 정보

            Args:
                connection   : 데이터베이스 연결 객체
                order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                [{'order_item_id': 3, 'order_detail_number': 'oidt00003', 'status': '배송중',
                'order_item_purchased_date': datetime.datetime(2020, 12, 31, 13, 25, 3), 'customer_phone': '01990103'}]

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT 
                order_item.id AS order_item_id,
                order_item.order_detail_number AS order_detail_number,
                order_item_status.`name` AS status,
                order_item.created_at AS order_item_purchased_date,
                `order`.sender_phone AS customer_phone
            FROM order_items AS order_item
                INNER JOIN orders AS `order` 
                    ON order_item.order_id = `order`.id
                INNER JOIN delivery_memo_types AS delivery_memo
                    ON `order`.delivery_memo_type_id = delivery_memo.id
                INNER JOIN products AS product 
                    ON order_item.product_id = product.id
                INNER JOIN sellers AS seller 
                    ON product.seller_id = seller.account_id
                INNER JOIN stocks AS stock 
                    ON order_item.stock_id = stock.id
                INNER JOIN colors AS color 
                    ON stock.color_id = color.id
                INNER JOIN sizes AS size 
                    ON stock.size_id = size.id
                INNER JOIN order_item_status_types AS order_item_status 
                    ON order_item.order_item_status_type_id = order_item_status.id
            WHERE order_item.id = %s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchall()
            if not result:
                raise DoesNotOrderDetail('주문 상세 정보가 존재하지 않습니다.')
            return result


    def get_product_info_dao(self, connection, order_item_id):
        """ 상품 정보

            Args:
                connection   : 데이터베이스 연결 객체
                order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                [{'product_number': 'P0000000000000000001', 'product_name': '성보의하루1', 'price': '10000 원 (할인가 9000원)',
                'discount_rate': Decimal('0.10'), 'brand_name': '나는셀러3',' option_information': 'Black/Free', 'qauntity': 1}]

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT 
                product.product_code AS product_number,
                product.`name` AS product_name,
                CONCAT(order_item.original_price ,' 원 (할인가 ', order_item.discounted_price, '원)') AS price,
                order_item.sale AS discount_rate,
                seller.`name` AS brand_name,
                CONCAT(color.`name`, '/', size.`name`) AS option_information,
                order_item.quantity AS qauntity
            FROM order_items AS order_item 
                INNER JOIN orders AS `order` 
                    ON order_item.order_id = `order`.id
                INNER JOIN delivery_memo_types AS delivery_memo
                    ON `order`.delivery_memo_type_id = delivery_memo.id
                INNER JOIN products AS product 
                    ON order_item.product_id = product.id
                INNER JOIN sellers AS seller 
                    ON product.seller_id = seller.account_id
                INNER JOIN stocks AS stock 
                    ON order_item.stock_id = stock.id
                INNER JOIN colors AS color 
                    ON stock.color_id = color.id
                INNER JOIN sizes AS size 
                    ON stock.size_id = size.id
                INNER JOIN order_item_status_types AS order_item_status 
                    ON order_item.order_item_status_type_id = order_item_status.id
            WHERE order_item.id = %s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchall()
            if not result:
                raise DoesNotOrderDetail('주문 상세 정보가 존재하지 않습니다.')
            return result


    def get_recipient_info_dao(self, connection, order_item_id):
        """ 수취자 정보

            Args:
                connection   : 데이터베이스 연결 객체
                        order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                [{'user_id': 102, 'customer_name': 'user2', 'recipient_name': '도우너', 'recipient_phone': '01055555555',
                'destination': '서울특별시 역삼동 (123321)', 'delivery_memo': '문

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT 
                `order`.user_id AS user_id,
                `order`.sender_name AS customer_name,
                `order`.recipient_name AS recipient_name,
                `order`.recipient_phone AS recipient_phone,
                CONCAT(`order`.address1, ' ', `order`.address2, ' (', `order`.post_number, ')') AS destination,
                delivery_memo.content AS delivery_memo
            FROM order_items AS order_item
                INNER JOIN orders AS `order` 
                    ON order_item.order_id = `order`.id
                INNER JOIN delivery_memo_types AS delivery_memo
                    ON `order`.delivery_memo_type_id = delivery_memo.id
                INNER JOIN products AS product 
                    ON order_item.product_id = product.id
                INNER JOIN sellers AS seller 
                    ON product.seller_id = seller.account_id
                INNER JOIN stocks AS stock
                    ON order_item.stock_id = stock.id
                INNER JOIN colors AS color 
                    ON stock.color_id = color.id
                INNER JOIN sizes AS size 
                    ON stock.size_id = size.id
                INNER JOIN order_item_status_types AS order_item_status 
                    ON order_item.order_item_status_type_id = order_item_status.id
            WHERE order_item.id = %s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchall()
            if not result:
                raise DoesNotOrderDetail('주문 상세 정보가 존재하지 않습니다.')
            return result


    def get_order_status_history_info_dao(self, connection, order_item_id):
        """ 주문 상태 변경 이력

            Args:
                connection   : 데이터베이스 연결 객체
                order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                [{'date': datetime.datetime(2021, 1, 3, 1, 27, 48), 'status': '배송중'},
                {'date': datetime.datetime(2020, 12, 31, 13, 25, 1), 'status': '상품준비'}]

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT 
                order_item_history.created_at AS `date`,
                order_item_status.`name` AS `status`
            FROM order_item_histories AS order_item_history
                JOIN order_item_status_types AS order_item_status
                    ON order_item_history.order_item_status_type_id = order_item_status.id
            WHERE 
                order_item_history.order_item_id = %s
            ORDER BY order_item_history.id DESC;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchall()
            if not result:
                raise DoesNotOrderDetail('주문 상세 정보가 존재하지 않습니다.')
            return result


    def get_updated_time_dao(self, connection, order_item_id):
        """ 업데이트 시각 이력

            Args:
                connection   : 데이터베이스 연결 객체
                order_item_id: 비지니스 레이어에서 넘겨 받은 인자

            Returns:
                (datetime.datetime(2020, 12, 31, 13, 25, 3),)

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            SELECT orders.updated_at
            FROM orders 
                INNER JOIN order_items
                    ON order_items.order_id = orders.id 
            WHERE order_items.id = %s;
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, order_item_id)
            result = cursor.fetchone()
            return result


    def update_sender_phone_dao(self, connection, data):
        """ 주문자 번호 수정

            Args:
                connection : 데이터베이스 연결 객체
                data       : 비지니스 레이어에서 넘겨 받은 data 객체

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            UPDATE orders 
            INNER JOIN order_items 
                ON orders.id = order_items.order_id
            SET sender_phone = %(sender_phone)s
            WHERE order_items.id = %(order_item_id)s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            affect_row = cursor.execute(sql, data)
            if affect_row == 0:
                raise DeniedUpdate('업데이트가 실행되지 않았습니다.')



    def update_recipient_phone_dao(self, connection, data):
        """ 수취자 연락처 수정

            Args:
                connection : 데이터베이스 연결 객체
                data       : 비지니스 레이어에서 넘겨 받은 data 객체

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
            UPDATE orders 
            INNER JOIN order_items 
                ON orders.id = order_items.order_id
            SET recipient_phone = %(recipient_phone)s 
            WHERE order_items.id = %(order_item_id)s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            affect_row = cursor.execute(sql, data)
            if affect_row == 0:
                raise DeniedUpdate('업데이트가 실행되지 않았습니다.')


    def update_address_dao(self, connection, data):
        """ 배송지 주소 수정

            Args:
                connection : 데이터베이스 연결 객체
                data       : 비지니스 레이어에서 넘겨 받은 data 객체

            History:
                2021-01-03(김민서): 작성
        """
        sql = """
        UPDATE orders
        INNER JOIN order_items ON orders.id = order_items.order_id
        SET address1 = %(address1)s, address2 = %(address2)s
        WHERE order_items.id = %(order_item_id)s;
        """

        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            affect_row = cursor.execute(sql, data)
            if affect_row == 0:
                raise DeniedUpdate('업데이트가 실행되지 않았습니다.')
