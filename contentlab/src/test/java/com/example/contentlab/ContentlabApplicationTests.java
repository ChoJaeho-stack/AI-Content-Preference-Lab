package com.example.contentlab;

import java.util.Base64;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
		"spring.jpa.database-platform=org.hibernate.dialect.MySQLDialect",
		"spring.jpa.properties.hibernate.boot.allow_jdbc_metadata_access=false",
		"spring.jpa.hibernate.ddl-auto=none",
		"spring.sql.init.mode=never"
})
class ContentlabApplicationTests {

	@MockitoBean
	private JdbcTemplate jdbc;

	@DynamicPropertySource
	static void testJwtKey(DynamicPropertyRegistry properties) {
		properties.add("JWT_SECRET", () -> Base64.getEncoder().encodeToString(new byte[32]));
	}

	@Test
	void contextLoads() {
	}

	@Test
	void recommendationRequiresAuthentication(
			@Autowired WebApplicationContext context, @Autowired FilterChainProxy security) throws Exception {
		MockMvcBuilders.webAppContextSetup(context).addFilters(security).build()
				.perform(post("/api/recommend"))
				.andExpect(status().isUnauthorized());
	}

}
