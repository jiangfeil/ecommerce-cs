SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS `customer_service`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `customer_service`;

CREATE TABLE IF NOT EXISTS `dialogue_states` (
  `sender_id` VARCHAR(64) NOT NULL COMMENT '用户唯一标识',
  `state_json` TEXT NOT NULL COMMENT '完整对话状态 JSON',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (`sender_id`)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
