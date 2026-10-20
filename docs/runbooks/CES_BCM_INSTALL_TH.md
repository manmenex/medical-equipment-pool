# คู่มือติดตั้งเครื่อง CES-BCM ทีละขั้น (ติดตั้ง อัปเดต ย้อนกลับ)

เอกสารนี้อธิบายสคริปต์ `setup-ces-bcm.ps1` และ `update-online.ps1`
(อยู่ใน `deployment/local-staging/`) สำหรับเครื่อง Windows 11 Pro ของหน่วยงาน
ชื่อ CES-BCM (i5-8500, RAM 8 GB, Docker Desktop แบบ Linux containers)

> **ข้อจำกัดที่ต้องรู้ก่อน**
> - เอกสารและสคริปต์นี้ **ไม่ได้ยืนยันว่าระบบพร้อมใช้งานจริง (production-ready)**
>   และ **ไม่ได้พิสูจน์เป้าหมาย RPO** การสำรองข้อมูลรายชั่วโมงเป็นเพียงกลไก
>   ต้องสังเกตผลจริงต่อเนื่องจึงจะอ้างได้
> - สคริปต์ผ่านการทดสอบอัตโนมัติด้วยตัวจำลอง (mock) เท่านั้น ยังไม่เคยรันบนเครื่อง
>   Windows จริง ให้ตรวจผลแต่ละขั้นด้วยตาเสมอ
> - **การนำขึ้นใช้งานจริงเป็นการตัดสินใจของ Owner** ระบบไม่อัปเดตตัวเอง
>   ไม่มีการตั้งเวลาอัปเดตอัตโนมัติ

## 1. สิ่งที่ต้องเตรียม

| รายการ | หมายเหตุ |
|---|---|
| เครื่อง Windows 11, บัญชีที่เป็น Administrator | RAM 8 GB, ที่ว่างดิสก์ 15 GB ขึ้นไป |
| อินเทอร์เน็ต (ครั้งแรก) | ถ้าไม่มี ให้ใช้ ZIP จาก USB (ข้อ 6) |
| PowerShell 7 | ถ้าเปิดด้วย PowerShell 5.1 สคริปต์จะพิมพ์คำสั่งติดตั้งให้ |
| ไฟล์ซอร์สโค้ด | GitHub > Code > Download ZIP แล้วแตกไฟล์ไว้ที่ใดก็ได้ (เช่น Desktop) |
| ไฟล์ CSV หอผู้ป่วย / หมวดอุปกรณ์ (ถ้ามี) | ข้อ 8.5 ของคู่มือ Local Staging; ไม่เก็บใน repository |
| OAuth client ID/secret ของ Google Drive (ถ้าจะตั้งสำรองข้อมูลไป Drive) | `PR24_BACKUP_RESTORE_RUNBOOK.md` ข้อ 12.2 |
| รหัสผ่าน Windows ของบัญชีที่ใช้รันงานสำรองข้อมูล | ใช้ตอนลงทะเบียน Task Scheduler เท่านั้น |

ไม่ต้องมี GitHub token (repository เป็น public) **ห้ามส่งรหัสผ่านหรือ token ให้ใคร
หรือเขียนลงไฟล์**

## 2. ลำดับการรัน (ติดตั้งครั้งแรก)

เปิด **PowerShell 7 แบบ Run as administrator** แล้วเข้าโฟลเดอร์ที่แตก ZIP:

```powershell
cd <โฟลเดอร์ที่แตก ZIP>\deployment\local-staging
.\setup-ces-bcm.ps1
```

ตัวเลือกที่พบบ่อย:

```powershell
# ระบุเวอร์ชัน (tag หรือ commit SHA) แทนค่าเริ่มต้น
.\setup-ces-bcm.ps1 -Version v1.0.0

# พร้อมโหลดข้อมูลหลัก
.\setup-ces-bcm.ps1 -WardsCsv D:\wards.csv -CategoriesCsv D:\categories.csv

# ไม่มีอินเทอร์เน็ต: ใช้ ZIP ของ commit ที่ระบุ
.\setup-ces-bcm.ps1 -SourceZip D:\mep.zip -Version <commit-sha>
```

ค่าเริ่มต้น: ติดตั้งที่ `C:\MEP\app` และบันทึกความคืบหน้าที่ `C:\MEP\setup-state.json`
ถ้าเวอร์ชันไม่ระบุ สคริปต์จะเลือก commit ล่าสุดของ branch หลักที่ **GitHub checks
ผ่านทั้งหมด** ถ้าถาม GitHub ไม่ได้ ต้องระบุ `-Version` เอง

ขั้นตอนที่สคริปต์ทำ (รันซ้ำได้ จะเริ่มต่อจากขั้นที่ยังไม่เสร็จ):

1. **preflight** ตรวจ Windows 11, สิทธิ์ Administrator, PowerShell 7, RAM, ที่ว่างดิสก์
2. **prerequisites** ตรวจ Docker Desktop และ Git ถ้าไม่มีจะ **ถามยืนยัน** ก่อนติดตั้งด้วย
   `winget install -e --id Docker.DockerDesktop` / `Git.Git` และเปิด WSL2
   แล้ว **หยุดให้คุณรีสตาร์ต Windows** (หรือเปิด PowerShell ใหม่) จากนั้นรันคำสั่งเดิมอีกครั้ง
3. **source** clone จาก `https://github.com/manmenex/medical-equipment-pool.git`
   ไปที่ `C:\MEP\app` และ checkout เวอร์ชันที่เลือก (บันทึกเวอร์ชันที่ติดตั้ง)
4. **install** รัน `install.ps1` เดิม จะถาม LAN URL, port และข้อมูลผู้ดูแลระบบ
   (รหัสผ่านชั่วคราวแสดงครั้งเดียวโดย backend)
5. **masterdata** ถ้าระบุ CSV ครบทั้งสองไฟล์ จะรัน `load-master-data.ps1 -Apply`
   ถ้าไม่ระบุ จะข้าม (ทำภายหลังได้)
6. **drive** ตั้งค่า Google Drive (`drive-backup.ps1 -Setup`): จะได้ URL และรหัส
   ให้เปิดบนอุปกรณ์ใดก็ได้ ล็อกอินด้วยบัญชี Gmail ของหน่วยงานแล้วกดอนุญาต
7. **schedule** ลงทะเบียนงานสำรองข้อมูลทุกชั่วโมง (`schedule-backup.ps1 -Install`)
   Windows จะถามรหัสผ่าน ส่งตรงให้ Task Scheduler สคริปต์ไม่เห็น ไม่เก็บ ไม่พิมพ์
8. **final** แสดง `status.ps1`, LAN URL และสรุปสิ่งที่เสร็จ/ค้างอยู่ (PENDING)

สคริปต์ **ไม่ลบข้อมูล ไม่ลบ volume ไม่ลบ backup ไม่ลบ `.env`** และไม่เคยรัน
`docker compose down -v`

### การเปิดระบบอัตโนมัติหลังไฟดับ (ทางเลือก)

สคริปต์แสดงขั้นตอนให้เท่านั้น ไม่ได้เปลี่ยนค่าใด ๆ: ตั้ง Docker Desktop ให้เริ่มเมื่อ
sign in และ (ถ้า Owner เห็นชอบ) ตั้ง auto sign-in ด้วย `netplwiz` หรือ Sysinternals
Autologon ข้อควรระวัง: ใครเปิดเครื่องได้ก็ใช้บัญชีนั้นได้ ควรตั้งเครื่องในห้องควบคุม

Firewall สำหรับเครื่องอื่นใน LAN สคริปต์ไม่ได้เปิดให้ ดูข้อ 2.5 ของคู่มือ Local Staging

## 3. อัปเดตผ่านอินเทอร์เน็ต (Owner เป็นผู้สั่งเท่านั้น)

```powershell
cd C:\MEP\app\deployment\local-staging
.\update-online.ps1 -Version v1.1.0      # tag หรือ commit SHA
```

ลำดับ: fetch จาก repository public > ตรวจว่ามี commit นั้นจริง และ GitHub checks
ผ่านทั้งหมด (ข้ามได้ด้วย `-Force` ซึ่งเป็นการตัดสินใจของ Owner) > **ปฏิเสธถ้า
working tree มีการแก้ไขค้างอยู่** > checkout แบบ detached > รัน `update.ps1`
(สำรองข้อมูลและตรวจสอบก่อนเสมอ "ไม่มี backup = ไม่อัปเดต") > บันทึกเวอร์ชันที่ติดตั้ง
และเวอร์ชันก่อนหน้า (`.version-history.json`)

ถ้า `update.ps1` ล้มเหลว โค้ดจะค้างที่เวอร์ชันใหม่ แต่ไม่มีการลบข้อมูล: รันคำสั่งเดิมซ้ำ
หรือใช้ `-Rollback` เพื่อกลับไปเวอร์ชันล่าสุดที่ใช้ได้

## 4. อัปเดตผ่าน USB (ไม่มีอินเทอร์เน็ต)

1. บนเครื่องที่มีอินเทอร์เน็ต: ไปหน้า commit ที่ต้องการบน GitHub > Code > Download ZIP
   (จดตัวอักษร commit SHA ไว้) แล้วคัดลอกใส่ USB
2. ที่ CES-BCM:

```powershell
.\update-online.ps1 -SourceZip E:\mep-<sha>.zip -Version <commit-sha>
```

สคริปต์อ่าน commit SHA จากตัว ZIP เองและเทียบกับ `-Version` ถ้าไม่ตรงหรืออ่านไม่ได้
จะปฏิเสธ ถ้าไม่ใส่ `-Version` จะเตือนว่า ZIP ไม่ได้รับการตรวจสอบ ออฟไลน์ตรวจ GitHub
checks ไม่ได้ จากนั้นสคริปต์ **แทนที่เฉพาะโค้ด** (คง `.env`, backups, logs, secrets) แล้วรัน
`update.ps1` ZIP ที่เก่ากว่าเวอร์ชันที่ติดตั้ง (มี migration น้อยกว่า) จะถูกปฏิเสธ

## 5. ย้อนกลับเวอร์ชัน (Rollback)

```powershell
.\update-online.ps1 -Rollback
```

- ย้อน **เฉพาะโค้ด** ไปเวอร์ชันก่อนหน้า แล้วรัน `update.ps1` (มี backup ก่อนเสมอ)
- **ไม่มีการ downgrade ฐานข้อมูลอัตโนมัติ** ถ้าเวอร์ชันใหม่เพิ่ม migration ที่เวอร์ชันเก่าไม่มี
  สคริปต์จะ **ปฏิเสธ** พร้อมรายชื่อ migration
- ถ้า Owner ตัดสินใจแล้วจริง ๆ ให้เพิ่ม `-ConfirmMigrationRollback` (ต้องมี backup ที่ตรวจสอบแล้ว):
  สคริปต์จะสลับโค้ดอย่างเดียว **ไม่รัน `update.ps1`** และพิมพ์ขั้นตอนกู้คืนฐานข้อมูล
  ซึ่งต้องทำด้วยมือโดย Owner กำกับตาม `PR24_BACKUP_RESTORE_RUNBOOK.md` ข้อ 12.6
  (ซ้อมก่อนด้วย `.\restore.ps1 -Backup <ไฟล์> -KeepRehearsalDatabase`)
  ไม่มีคำสั่งเดียวที่ restore ทับฐานข้อมูลจริง โดยตั้งใจ

## 6. แก้ปัญหาเบื้องต้น

| อาการ | ทำอย่างไร |
|---|---|
| เปิดด้วย PowerShell 5.1 แล้วสคริปต์หยุด | รัน `winget install -e --id Microsoft.PowerShell` แล้วเปิด "PowerShell 7" แบบ Administrator |
| Preflight ไม่ผ่าน | แก้ตามรายการที่แสดง (สิทธิ์ Admin, RAM, ที่ว่างดิสก์) แล้วรันซ้ำ |
| หยุดที่ prerequisites หลังติดตั้ง Docker/Git | รีสตาร์ต Windows หรือเปิด PowerShell ใหม่ เปิด Docker Desktop จนขึ้น Engine running แล้วรันคำสั่งเดิม |
| Could not query GitHub | ระบุ `-Version <tag หรือ sha>` เอง หรือใช้ `-SourceZip` |
| ... does not have all GitHub checks green | เลือกเวอร์ชันอื่น; ใช้ `-Force` ต่อเมื่อ Owner ตัดสินใจแล้ว |
| has local changes | มีไฟล์ในโฟลเดอร์ซอร์สถูกแก้ อย่าลบเอง แจ้งผู้ดูแลระบบ |
| อยากเริ่มขั้นตอนใหม่ / ล้างการ resume | ไฟล์ความคืบหน้าอยู่ที่ `C:\MEP\setup-state.json` (โฟลเดอร์แม่ของ `-InstallDir`) เปลี่ยนชื่อไฟล์นี้ (เช่น เป็น `setup-state.old.json`) แล้วรัน `setup-ces-bcm.ps1` ใหม่ ขั้นตอนจะเริ่มจากต้น แต่ install.ps1 และ clone รันซ้ำได้อย่างปลอดภัย ข้อมูล backup และ `.env` ไม่ถูกลบ |
| แทนที่โค้ดจาก ZIP ล้มเหลวกลางทาง | สคริปต์ย้อนไฟล์เดิมกลับให้เอง; ถ้าแจ้งว่ากู้คืนไม่ครบ ไฟล์เดิมอยู่ในโฟลเดอร์ `.mep-old-*` ข้างโฟลเดอร์ติดตั้ง อย่าลบ แจ้งผู้ดูแลระบบ; โฟลเดอร์ `.mep-staging-*`/`.mep-peek-*` ที่ค้างลบได้ภายหลัง |
| state file unreadable | ไฟล์ `C:\MEP\setup-state.json` เสีย ให้เปลี่ยนชื่อไฟล์แล้วรันซ้ำ (สิ่งที่ติดตั้งแล้วไม่ถูกแตะ) |
| install/drive/schedule ล้มเหลว | อ่านข้อความ ERROR/ACTION แล้วรันคำสั่งเดิมซ้ำ ขั้นที่เสร็จแล้วจะไม่ทำซ้ำ |
| อย่างอื่น | ดูข้อ 8 ของ `PR24_LOCAL_STAGING_INSTALLATION_RUNBOOK.md` และ **อย่าแก้ฐานข้อมูลหรือ Docker volume เอง** |

## 7. สิ่งที่ยังไม่ได้ตรวจบนเครื่องจริง

winget/Docker Desktop/WSL2 บน Windows 11 จริง, การคัดลอกไฟล์ตอนแทนที่โค้ดจาก ZIP,
การลงทะเบียน Task Scheduler ด้วยรหัสผ่าน และ OAuth device flow ของ Google
ต้องให้ Owner ตรวจและบันทึกผลระหว่างติดตั้งครั้งแรก
