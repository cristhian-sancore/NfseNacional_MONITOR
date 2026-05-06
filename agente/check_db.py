import fdb
con = fdb.connect(
    host='localhost', 
    port=3050, 
    database=r'C:\Fiorilli\BANCOS\SGB_DADOS\SIADADOS.FDB', 
    user='fscsia', 
    password='csfais', 
    charset='WIN1252'
)
cur = con.cursor()
cur.execute("SELECT RDB$FIELD_NAME FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = 'NFE_LOG_ERROS'")
print([r[0].strip() for r in cur.fetchall()])
con.close()
