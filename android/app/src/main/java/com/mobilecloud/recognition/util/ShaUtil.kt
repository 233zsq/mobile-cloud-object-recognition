package com.mobilecloud.recognition.util

import java.security.MessageDigest

/** 哈希工具：模型包交接要求校验 SHA-256（见 docs/model-contract.md） */
object ShaUtil {
    fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
